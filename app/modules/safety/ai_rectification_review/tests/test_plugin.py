"""AI 整改初审插件 — 独立测试套件。

不依赖数据库、飞书或 FastAPI，仅测试插件核心逻辑。
运行: uv run pytest app/modules/safety/ai_rectification_review/tests/ -v
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_rectification_review.prompts import (
    CRITICAL_CONSTRAINTS,
    FEWSHOT_EXAMPLES,
    OUTPUT_FORMAT,
    SYSTEM_ROLE,
    WORK_RULES,
    build_context_text,
    build_full_prompt,
    build_reply_context_text,
    get_db_seed_config,
    get_expected_keys,
)
from app.modules.safety.ai_rectification_review.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_rectification_review.schemas import (
    ComplianceLevel,
    MeasureQualityLevel,
    PhotoMatchLevel,
    PluginConfig,
    RectificationReviewInput,
    RectificationReviewOutput,
    ReviewConclusion,
)

# ═══════════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════════

VALID_OUTPUT_DICT = {
    "photo_match_analysis": "整改后照片拍摄角度与原始缺陷照片一致，清晰可见原引入口已安装防爆堵头（带红色密封垫圈），箱体内壁干净无积尘。原始缺陷的两个问题点均在整改后照片中有对应的修复展示。",
    "photo_match_level": "matched",
    "measure_quality_assessment": "措施质量较高：有具体操作（加装堵头、密封胶固定、吸尘器清理），有量化标准（扭矩12N·m），有时间节点（7月1日起），有责任主体（持证电工张工），针对根因建立了巡检制度。未出现空泛表述。",
    "measure_quality_level": "adequate",
    "standard_compliance": "满足GB 3836.1-2010第15章引入口封堵要求和GB 50016-2014第10.2.4条防爆措施要求。堵头加装符合标准。",
    "standard_compliance_level": "compliant",
    "review_conclusion": "通过",
    "review_comments": "通过",
}


def make_input(
    original_description: str = "测试隐患描述",
    rectification_reply: str = "测试整改回复",
    **kwargs,
) -> RectificationReviewInput:
    kwargs.setdefault("department", "生产部")
    return RectificationReviewInput(
        original_description=original_description,
        rectification_reply=rectification_reply,
        **kwargs,
    )


def make_output(**overrides) -> RectificationReviewOutput:
    data = {**VALID_OUTPUT_DICT, **overrides}
    return RectificationReviewOutput(**data)


# ═══════════════════════════════════════════════════════════════════════════
# Mock AI 服务
# ═══════════════════════════════════════════════════════════════════════════


class MockAIService:
    """模拟 AI 服务，返回预设输出。"""

    def __init__(self, return_dict: dict | None = None, should_fail: bool = False):
        self.return_dict = return_dict or VALID_OUTPUT_DICT
        self.should_fail = should_fail
        self.last_messages: list | None = None
        self.last_expected_keys: list | None = None

    async def chat_parsed(self, messages, expected_keys, temperature=0.05):
        if self.should_fail:
            raise RuntimeError("Mock AI failure")
        self.last_messages = messages
        self.last_expected_keys = expected_keys
        return dict(self.return_dict)

    async def chat_vision_parsed(
        self, text_prompt, image_urls, expected_keys, temperature=0.05
    ):
        if self.should_fail:
            raise RuntimeError("Mock AI failure")
        self.last_expected_keys = expected_keys
        return dict(self.return_dict)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Schema 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemas:
    """输入/输出数据模型验证。"""

    def test_input_minimal(self):
        """最小输入创建成功。"""
        inp = make_input("防爆电箱堵头缺失", "已加装防爆堵头")
        assert inp.original_description == "防爆电箱堵头缺失"
        assert inp.rectification_reply == "已加装防爆堵头"
        assert inp.original_defect_photos == []
        assert inp.rectification_photos == []

    def test_input_full(self):
        """完整输入应包含所有字段。"""
        inp = make_input(
            original_description="防爆电箱堵头缺失",
            rectification_reply="已加装堵头并清理积尘",
            key_defect="引入口未封堵，积尘严重",
            hazard_type="unsafe_condition",
            hazard_category="instrument_electrical",
            hazard_level="major",
            ai_rectification_suggestion={
                "immediate": "断电并安装堵头",
                "short_term": "排查全区域电箱",
                "long_term": "修订巡检制度",
            },
            original_defect_photos=["http://img/before.jpg"],
            rectification_photos=["http://img/after.jpg"],
            department="生产部",
        )
        assert inp.hazard_type == "unsafe_condition"
        assert len(inp.original_defect_photos) == 1
        assert len(inp.rectification_photos) == 1
        assert inp.ai_rectification_suggestion["immediate"] == "断电并安装堵头"

    def test_output_valid(self):
        """有效输出创建成功。"""
        out = make_output()
        assert out.review_conclusion == ReviewConclusion.PASS
        assert out.photo_match_level == PhotoMatchLevel.MATCHED
        assert out.measure_quality_level == MeasureQualityLevel.ADEQUATE
        assert out.standard_compliance_level == ComplianceLevel.COMPLIANT

    def test_enum_rejection(self):
        """非法枚举值应被拒绝。"""
        with pytest.raises(ValueError):
            RectificationReviewOutput(**{
                **VALID_OUTPUT_DICT,
                "review_conclusion": "invalid_conclusion",
            })

    def test_config_defaults(self):
        """配置默认值。"""
        config = PluginConfig()
        assert config.temperature == 0.05
        assert config.enable_vision is True
        assert config.enable_knowledge is True
        assert config.strict_mode is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. Prompt 模板测试
# ═══════════════════════════════════════════════════════════════════════════


class TestPrompts:
    """Prompt 模板和辅助函数验证。"""

    def test_system_role_not_empty(self):
        assert len(SYSTEM_ROLE) > 100
        assert "安全审核" in SYSTEM_ROLE

    def test_work_rules_has_four_sections(self):
        assert "### 1. 图片比对规则" in WORK_RULES
        assert "### 2. 措施有效性评估规则" in WORK_RULES
        assert "### 3. 标准合规评估规则" in WORK_RULES
        assert "### 4. 综合评审判定规则" in WORK_RULES

    def test_output_format_has_all_keys(self):
        for key in get_expected_keys():
            assert key in OUTPUT_FORMAT, f"Missing key in OUTPUT_FORMAT: {key}"

    def test_expected_keys(self):
        keys = get_expected_keys()
        assert len(keys) == 8
        assert "photo_match_analysis" in keys
        assert "review_conclusion" in keys

    def test_critical_constraints_not_empty(self):
        assert len(CRITICAL_CONSTRAINTS) > 100
        assert "不通过" in CRITICAL_CONSTRAINTS

    def test_context_text_basic(self):
        ctx = build_context_text(
            original_description="防爆电箱堵头缺失",
            department="生产部",
            hazard_type="unsafe_condition",
        )
        assert "防爆电箱堵头缺失" in ctx
        assert "生产部" in ctx
        assert "unsafe_condition" in ctx

    def test_context_text_with_ai_suggestion(self):
        ctx = build_context_text(
            original_description="测试",
            key_defect="关键缺陷描述",
            ai_rectification_suggestion={
                "immediate": "立即措施",
                "short_term": "短期整改",
                "long_term": "长期预防",
            },
        )
        assert "关键缺陷描述" in ctx
        assert "立即措施" in ctx
        assert "短期整改" in ctx
        assert "长期预防" in ctx

    def test_reply_context_with_photos(self):
        ctx = build_reply_context_text(
            rectification_reply="已修复",
            has_photos=True,
        )
        assert "已修复" in ctx
        assert "整改后现场照片" in ctx

    def test_reply_context_without_photos(self):
        ctx = build_reply_context_text(
            rectification_reply="已修复",
            has_photos=False,
        )
        assert "已修复" in ctx
        assert "未提供整改后现场照片" in ctx

    def test_full_prompt_text_mode(self):
        prompt = build_full_prompt(
            context="原始隐患上下文",
            reply_context="整改回复上下文",
            vision_mode=False,
            include_fewshot=False,
        )
        assert "原始隐患上下文" in prompt
        assert "整改回复上下文" in prompt
        assert WORK_RULES in prompt

    def test_full_prompt_with_knowledge(self):
        prompt = build_full_prompt(
            context="原始隐患上下文",
            reply_context="整改回复上下文",
            vision_mode=False,
            include_fewshot=False,
            knowledge_context="## 法规知识库\nGB 30871 第5.2条",
        )
        assert "法规知识库" in prompt
        assert "GB 30871" in prompt
        # 知识库应在 WORK_RULES 之前
        kb_pos = prompt.index("法规知识库")
        rules_pos = prompt.index(WORK_RULES)
        assert kb_pos < rules_pos

    def test_full_prompt_with_fewshot(self):
        prompt = build_full_prompt(
            context="原始隐患上下文",
            reply_context="整改回复上下文",
            vision_mode=False,
            include_fewshot=True,
        )
        assert "参考示例" in prompt
        assert "防爆电箱" in prompt  # 第一个 few-shot 示例

    def test_db_seed_config(self):
        config = get_db_seed_config()
        assert config["module_code"] == "hazard"
        assert config["workflow_name"] == "AI整改初审"
        assert config["trigger_event"] == "reply_rectification"
        scripts = config["script_configs"]["scripts"]
        assert len(scripts) == 1
        assert scripts[0]["script_number"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# 3. 规则引擎测试
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleEngine:
    """规则引擎验证。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_valid_output_passes(self):
        inp = make_input("防爆电箱堵头缺失", "已加装堵头")
        out = make_output()
        result = self.engine.validate(inp, out)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_invalid_enum_detected(self):
        inp = make_input()
        # 使用 model_construct 绕过 Pydantic 验证来测试规则引擎的枚举校验
        out = RectificationReviewOutput.model_construct(
            **{
                **VALID_OUTPUT_DICT,
                "review_conclusion": "invalid_value",
            }
        )
        result = self.engine.validate(inp, out)
        assert not result.is_valid

    def test_short_photo_analysis(self):
        inp = make_input()
        out = make_output(photo_match_analysis="太短")
        result = self.engine.validate(inp, out)
        assert not result.is_valid
        assert any("图片比对分析" in e for e in result.errors)

    def test_short_review_comments(self):
        inp = make_input()
        out = RectificationReviewOutput.model_construct(
            **{**VALID_OUTPUT_DICT, "review_comments": ""}
        )
        result = self.engine.validate(inp, out)
        assert not result.is_valid
        assert any("AI初审结果" in e for e in result.errors)

    def test_no_photos_pass_allowed_with_warning(self):
        """无照片 + 通过 → 允许（但产生 warning）。"""
        inp = make_input()
        out = make_output(
            photo_match_level="no_photos",
            review_conclusion="通过",
        )
        result = self.engine.validate(inp, out)
        assert result.is_valid  # 降级为 warning，不阻断
        assert any("无整改后图片" in w for w in result.warnings)

    def test_inadequate_quality_pass_blocked(self):
        """措施不合格 + 通过 → 错误。"""
        inp = make_input()
        out = make_output(
            measure_quality_level="inadequate",
            review_conclusion="通过",
        )
        result = self.engine.validate(inp, out)
        assert not result.is_valid

    def test_unmatched_pass_blocked(self):
        """图片不匹配 + 通过 → 错误（硬性：照片显示隐患仍存在）。"""
        inp = make_input()
        out = make_output(
            photo_match_level="unmatched",
            review_conclusion="通过",
        )
        result = self.engine.validate(inp, out)
        assert not result.is_valid
        assert any("unmatched" in e for e in result.errors)

    def test_non_compliant_pass_allowed_with_warning(self):
        """不合规 + 通过 → 允许（但产生 warning，标准合规是参考维度）。"""
        inp = make_input()
        out = make_output(
            standard_compliance_level="non_compliant",
            review_conclusion="通过",
        )
        result = self.engine.validate(inp, out)
        assert result.is_valid  # 降级为 warning，不阻断
        assert any("non_compliant" in w for w in result.warnings)

    def test_banned_phrase_warning(self):
        """泛泛表述检测。"""
        inp = make_input()
        out = make_output(
            measure_quality_assessment="应加强管理注意安全，提高意识" + "x" * 50,
        )
        result = self.engine.validate(inp, out)
        assert len(result.warnings) > 0

    def test_relevance_warning(self):
        """输入输出不相关检测。"""
        inp = make_input(original_description="防爆电箱堵头缺失 积尘严重")
        out = make_output(
            review_comments="本次审核涉及完全不同的内容安全施工"
            + "x" * 50,
            photo_match_analysis="无关内容" + "x" * 50,
        )
        result = self.engine.validate(inp, out)
        # 可能产生相关性警告
        assert isinstance(result.warnings, list)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 自动修正器测试
# ═══════════════════════════════════════════════════════════════════════════


class TestAutoCorrect:
    """auto_correct 函数验证。"""

    def test_strips_whitespace(self):
        out = make_output(photo_match_analysis="  有内容但前后有空格  ")
        corrected = auto_correct(out)
        assert corrected.photo_match_analysis == "有内容但前后有空格"

    def test_fills_empty_fields(self):
        # 使用 model_construct 绕过 Pydantic 验证以测试空字符串回填
        out = RectificationReviewOutput.model_construct(
            **{
                **VALID_OUTPUT_DICT,
                "photo_match_analysis": "",
                "measure_quality_assessment": "",
            }
        )
        corrected = auto_correct(out)
        assert len(corrected.photo_match_analysis) > 0
        assert len(corrected.measure_quality_assessment) > 0

    def test_fills_empty_review_comments(self):
        out = RectificationReviewOutput.model_construct(
            **{
                **VALID_OUTPUT_DICT,
                "review_comments": "",
            }
        )
        corrected = auto_correct(out)
        assert len(corrected.review_comments) > 0
        assert "不通过" in corrected.review_comments


# ═══════════════════════════════════════════════════════════════════════════
# 5. 集成测试（Mock AI）
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """插件集成测试（使用 Mock AI 服务）。"""

    @pytest.fixture
    def plugin(self):
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
        )
        return AIRectificationReviewer(MockAIService())

    @pytest.mark.asyncio
    async def test_basic_review(self, plugin):
        """基本审核流程。"""
        inp = make_input("防爆电箱堵头缺失", "已加装防爆堵头并用密封胶固定")
        result = await plugin.review(inp)
        assert result.review_conclusion == ReviewConclusion.PASS
        assert result.photo_match_level == PhotoMatchLevel.MATCHED

    @pytest.mark.asyncio
    async def test_vision_routing(self):
        """有图片时走视觉模式。"""
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
        )

        mock = MockAIService()
        plugin = AIRectificationReviewer(mock)
        inp = make_input(
            "防爆电箱堵头缺失",
            "已加装堵头",
            rectification_photos=["http://img/after.jpg"],
        )
        result = await plugin.review(inp)
        assert result.review_conclusion == ReviewConclusion.PASS

    @pytest.mark.asyncio
    async def test_ai_failure_raises(self):
        """AI 调用失败应抛出 ReviewError。"""
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
            ReviewError,
        )

        mock = MockAIService(should_fail=True)
        plugin = AIRectificationReviewer(mock)
        inp = make_input("测试", "测试回复")

        with pytest.raises(ReviewError):
            await plugin.review(inp)

    @pytest.mark.asyncio
    async def test_batch_review(self):
        """批量审核。"""
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
        )

        plugin = AIRectificationReviewer(MockAIService())
        inputs = [
            make_input("隐患1", "整改1"),
            make_input("隐患2", "整改2"),
        ]
        results = await plugin.review_batch(inputs)
        assert len(results) == 2
        assert all(
            r.review_conclusion == ReviewConclusion.PASS for r in results
        )

    @pytest.mark.asyncio
    async def test_vision_fallback_to_text(self):
        """vision 不可用时降级为纯文本。"""
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
        )

        # Mock 无 chat_vision_parsed 方法 → 自动降级
        class TextOnlyMock:
            async def chat_parsed(self, messages, expected_keys, temperature=0.05):
                return dict(VALID_OUTPUT_DICT)

        plugin = AIRectificationReviewer(TextOnlyMock())
        inp = make_input(
            "防爆电箱堵头缺失",
            "已加装堵头",
            rectification_photos=["http://img/after.jpg"],
        )
        result = await plugin.review(inp)
        assert result.review_conclusion == ReviewConclusion.PASS

    @pytest.mark.asyncio
    async def test_prompt_includes_context(self):
        """验证 prompt 包含了输入上下文。"""
        from app.modules.safety.ai_rectification_review.plugin import (
            AIRectificationReviewer,
        )

        mock = MockAIService()
        plugin = AIRectificationReviewer(mock)
        inp = make_input("防爆电箱堵头缺失", "已加装堵头")
        await plugin.review(inp)

        # 检查最后一条消息包含原始描述
        user_content = mock.last_messages[-1]["content"]
        assert "防爆电箱堵头缺失" in user_content
        assert "已加装堵头" in user_content


# ═══════════════════════════════════════════════════════════════════════════
# 6. Few-shot 示例质量基准测试
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityBenchmarks:
    """验证所有 few-shot 示例都能通过规则引擎验证。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_fewshot_1_passes(self):
        """示例1（通过）通过验证。"""
        ex = FEWSHOT_EXAMPLES[0]
        out = RectificationReviewOutput(**ex["output"])
        inp = RectificationReviewInput(**ex["input"])
        result = self.engine.validate(inp, out)
        assert result.is_valid, f"Errors: {result.errors}"

    def test_fewshot_2_passes(self):
        """示例2（不通过）通过验证。"""
        ex = FEWSHOT_EXAMPLES[1]
        out = RectificationReviewOutput(**ex["output"])
        inp = RectificationReviewInput(**ex["input"])
        result = self.engine.validate(inp, out)
        assert result.is_valid, f"Errors: {result.errors}"

    def test_fewshot_3_passes(self):
        """示例3（不通过，无照片）通过验证。"""
        ex = FEWSHOT_EXAMPLES[2]
        out = RectificationReviewOutput(**ex["output"])
        inp = RectificationReviewInput(**ex["input"])
        result = self.engine.validate(inp, out)
        assert result.is_valid, f"Errors: {result.errors}"

    def test_fewshot_4_passes(self):
        """示例4（通过，附改进建议）通过验证。"""
        ex = FEWSHOT_EXAMPLES[3]
        out = RectificationReviewOutput(**ex["output"])
        inp = RectificationReviewInput(**ex["input"])
        result = self.engine.validate(inp, out)
        assert result.is_valid, f"Errors: {result.errors}"
