"""AI隐患识别插件 — 独立测试套件。

不依赖数据库、飞书或 FastAPI，仅测试插件核心逻辑。
运行: uv run pytest app/modules/safety/ai_hazard_identification/tests/ -v
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_hazard_identification.prompts import (
    FEWSHOT_EXAMPLES,
    OUTPUT_FORMAT,
    SYSTEM_ROLE,
    WORK_RULES,
    build_context_text,
    build_full_prompt,
    get_db_seed_config,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_identification.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardCategoryEnum,
    HazardIdentificationInput,
    HazardIdentificationOutput,
    HazardLevelEnum,
    HazardTypeEnum,
    PluginConfig,
    RectificationSuggestion,
)

# ═══════════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════════

VALID_OUTPUT_DICT = {
    "key_defect": "防爆电箱接线口未用堵头封堵，箱内积尘严重，存在爆炸风险",
    "hazard_type": "unsafe_condition",
    "hazard_category": "instrument_electrical",
    "hazard_level": "major",
    "rectification_suggestion": {
        "corrective": "立即加装防爆堵头，使用吸尘器清理箱内积尘，一周内排查全区域所有防爆电箱确保封堵完好",
        "preventive": "修订防爆设备巡检制度，将封堵检查纳入周检，建立防爆设备全生命周期台账",
    },
    "major_hazard_basis": "《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准》第十条：爆炸危险场所未按国家标准安装使用防爆电气设备；GB 3836.1-2010 第15章",
}


def make_input(description: str = "测试隐患", **kwargs) -> HazardIdentificationInput:
    kwargs.setdefault("department", "生产部")
    kwargs.setdefault("location", "合成车间")
    return HazardIdentificationInput(description=description, **kwargs)


def make_output(**overrides) -> HazardIdentificationOutput:
    data = {**VALID_OUTPUT_DICT, **overrides}
    return HazardIdentificationOutput(**data)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Schema 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemas:
    """输入/输出数据模型验证。"""

    def test_input_minimal(self):
        """最小输入（只有描述）应该创建成功。"""
        inp = make_input("防爆电箱堵头缺失")
        assert inp.description == "防爆电箱堵头缺失"
        assert inp.defect_photos == []

    def test_input_full(self):
        """完整输入应包含所有字段。"""
        inp = HazardIdentificationInput(
            hazard_no="HZ-2026-0001",
            description="管道法兰垫片泄漏",
            department="生产部",
            location="合成车间二楼",
            discovered_by_name="张三",
            defect_photos=["https://example.com/photo.jpg"],
        )
        assert inp.hazard_no == "HZ-2026-0001"
        assert len(inp.defect_photos) == 1

    def test_output_from_valid_dict(self):
        """有效字典应成功构建输出。"""
        output = HazardIdentificationOutput(**VALID_OUTPUT_DICT)
        assert output.hazard_type == HazardTypeEnum.UNSAFE_CONDITION
        assert output.hazard_category == HazardCategoryEnum.INSTRUMENT_ELECTRICAL
        assert output.hazard_level == HazardLevelEnum.MAJOR
        assert output.rectification_suggestion.corrective

    def test_output_invalid_enum_rejected(self):
        """无效枚举值应被 Pydantic 拒绝。"""
        with pytest.raises(ValueError):
            HazardIdentificationOutput(**{**VALID_OUTPUT_DICT, "hazard_type": "invalid_type"})

    def test_plugin_config_defaults(self):
        """默认配置应合理。"""
        config = PluginConfig()
        assert config.temperature == 0.05
        assert config.strict_mode is True
        assert config.enable_vision is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. Prompt 模板测试
# ═══════════════════════════════════════════════════════════════════════════


class TestPrompts:
    """Prompt 构建测试。"""

    def test_system_role_not_empty(self):
        assert len(SYSTEM_ROLE) > 100

    def test_work_rules_contains_all_sections(self):
        sections = ["隐患分类判定规则", "隐患类别判定规则", "隐患级别判定规则", "整改建议生成规则", "判定依据引用规则"]
        for section in sections:
            assert section in WORK_RULES, f"缺少规则节: {section}"

    def test_work_rules_contains_shutdown_criterion(self):
        """隐患级别判定规则应包含停产整改判断（新增最高优先级）。"""
        assert "停产整改判断" in WORK_RULES
        assert "全厂停产或全车间停产" in WORK_RULES
        assert "局部停产" in WORK_RULES

    def test_output_format_is_valid_json_template(self):
        # 输出格式应该是一个描述（不是 JSON，因为在 Python 字符串里）
        assert "key_defect" in OUTPUT_FORMAT
        assert "hazard_type" in OUTPUT_FORMAT
        assert "rectification_suggestion" in OUTPUT_FORMAT
        assert "corrective" in OUTPUT_FORMAT
        assert "preventive" in OUTPUT_FORMAT

    def test_expected_keys(self):
        keys = get_expected_keys()
        assert "key_defect" in keys
        assert "hazard_type" in keys
        assert "hazard_category" in keys
        assert "hazard_level" in keys
        assert "rectification_suggestion" in keys
        assert "major_hazard_basis" in keys
        assert len(keys) == 6

    def test_fewshot_examples_complete(self):
        """4 个 few-shot 示例应覆盖 4 种隐患分类。"""
        assert len(FEWSHOT_EXAMPLES) == 4
        types = {ex["output"]["hazard_type"] for ex in FEWSHOT_EXAMPLES}
        assert types == {
            "unsafe_condition",
            "unsafe_action",
            "environmental",
            "management_defect",
        }

    def test_fewshot_examples_have_valid_enums(self):
        """Few-shot 示例的枚举值应合法。"""
        valid_types = {e.value for e in HazardTypeEnum}
        valid_cats = {e.value for e in HazardCategoryEnum}
        valid_levels = {e.value for e in HazardLevelEnum}
        for ex in FEWSHOT_EXAMPLES:
            assert ex["output"]["hazard_type"] in valid_types
            assert ex["output"]["hazard_category"] in valid_cats
            assert ex["output"]["hazard_level"] in valid_levels

    def test_fewshot_examples_have_two_tier_rectification(self):
        """Few-shot 示例的整改建议应使用两层结构。"""
        for ex in FEWSHOT_EXAMPLES:
            rs = ex["output"]["rectification_suggestion"]
            assert "corrective" in rs, f"缺少 corrective 字段"
            assert "preventive" in rs, f"缺少 preventive 字段"
            assert len(rs["corrective"]) > 30
            assert len(rs["preventive"]) > 20

    def test_fewshot_example1_demonstrates_shutdown_priority(self):
        """示例1（防爆电箱堵头）应演示停产整改优先判定：加装堵头无需断电 → general。"""
        ex1 = FEWSHOT_EXAMPLES[0]
        assert ex1["output"]["hazard_level"] == "general", \
            "示例1应判定为general（加装堵头无需设备断电，可直接在线操作）"
        assert "无需设备断电" in ex1["output"]["rectification_suggestion"]["corrective"] or \
               "无需断电" in ex1["output"]["rectification_suggestion"]["corrective"], \
            "示例1的整改措施应明确标注加装堵头无需断电"

    def test_build_context_text(self):
        text = build_context_text(
            hazard_no="HZ-001",
            description="管道泄漏",
            department="生产部",
            location="合成车间",
        )
        assert "HZ-001" in text
        assert "管道泄漏" in text
        assert "生产部" in text
        assert "合成车间" in text

    def test_build_full_prompt_includes_all_sections(self):
        prompt = build_full_prompt("测试上下文", vision_mode=False, include_fewshot=True)
        assert "测试上下文" in prompt
        assert "工作规则" in prompt
        assert "输出格式" in prompt
        assert "参考示例" in prompt
        assert "示例1" in prompt
        assert "示例4" in prompt

    def test_build_full_prompt_without_fewshot(self):
        prompt = build_full_prompt("测试", vision_mode=False, include_fewshot=False)
        assert "参考示例" not in prompt

    def test_get_db_seed_config(self):
        config = get_db_seed_config()
        assert config["module_code"] == "hazard"
        assert config["is_enabled"] is True
        assert "scripts" in config["script_configs"]
        assert len(config["script_configs"]["scripts"]) == 2
        assert config["script_configs"]["scripts"][0]["script_number"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. 规则引擎测试
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleEngine:
    """规则引擎验证。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_valid_output_passes(self):
        result = self.engine.validate(make_input(), make_output())
        assert result.is_valid, f"Unexpected errors: {result.errors}"

    def test_invalid_enum_detected(self):
        # 绕过 Pydantic 枚举校验，直接构造以测试 RuleEngine 的枚举验证
        output = HazardIdentificationOutput.model_construct(
            **{**VALID_OUTPUT_DICT, "hazard_type": "invalid"}
        )
        result = self.engine.validate(make_input(), output)
        assert not result.is_valid
        assert any("隐患分类" in e for e in result.errors)

    def test_short_key_defect_detected(self):
        output = make_output(key_defect="很短")
        result = self.engine.validate(make_input(), output)
        assert not result.is_valid
        assert any("过短" in e for e in result.errors)

    def test_empty_rectification_detected(self):
        output = make_output(rectification_suggestion=RectificationSuggestion(
            corrective="", preventive=""
        ))
        result = self.engine.validate(make_input(), output)
        assert not result.is_valid
        assert len([e for e in result.errors if "不能为空" in e]) == 2

    def test_basis_too_short_detected(self):
        # 5-19 字的依据（通过 Pydantic min_length=5，但触发 RuleEngine <20 检查）
        output = make_output(major_hazard_basis="这是一个很短的依据文本")
        result = self.engine.validate(make_input(), output)
        assert not result.is_valid
        assert any("过短" in e for e in result.errors)

    def test_banned_phrase_detected(self):
        output = make_output(rectification_suggestion=RectificationSuggestion(
            corrective="加强管理，注意安全",
            preventive="需加强培训，提高意识",
        ))
        result = self.engine.validate(make_input(), output)
        assert any("加强管理" in w for w in result.warnings)

    def test_no_regulation_ref_detected(self):
        output = make_output(major_hazard_basis="这是一个隐患，需要立即整改处理")
        result = self.engine.validate(make_input(), output)
        assert not result.is_valid
        assert any("法规" in e for e in result.errors)

    def test_consistency_warning(self):
        # 物的不安全状态 对应 三违作业 不太合理
        output = make_output(
            hazard_type="unsafe_condition",
            hazard_category="violation_operation",
        )
        result = self.engine.validate(make_input(), output)
        assert result.is_valid  # consistency 只是 warning 不阻塞
        assert any("关联性较低" in w for w in result.warnings)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 自动修正测试
# ═══════════════════════════════════════════════════════════════════════════


class TestAutoCorrect:
    """自动修正功能测试。"""

    def test_strips_key_defect(self):
        output = make_output(key_defect="  多余的空白描述  ")
        corrected = auto_correct(output)
        assert corrected.key_defect == "多余的空白描述"

    def test_fills_empty_rectification(self):
        output = make_output(rectification_suggestion=RectificationSuggestion(
            corrective="具体措施", preventive=""
        ))
        corrected = auto_correct(output)
        assert corrected.rectification_suggestion.preventive != ""
        assert "整改方案" in corrected.rectification_suggestion.preventive


# ═══════════════════════════════════════════════════════════════════════════
# 5. 集成测试（Mock AI Service）
# ═══════════════════════════════════════════════════════════════════════════


class MockAIService:
    """Mock AI 服务，返回固定的标准输出。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0
        self.last_messages = None

    async def chat_parsed(self, messages, expected_keys, temperature=0.1):
        self.call_count += 1
        self.last_messages = messages
        if self.fail:
            raise Exception("模拟 AI 调用失败")
        return {**VALID_OUTPUT_DICT}

    async def chat_vision_parsed(self, text_prompt, image_urls, expected_keys, temperature=0.1):
        self.call_count += 1
        self.last_messages = [{"role": "user", "content": text_prompt}]
        if self.fail:
            raise Exception("模拟 Vision AI 调用失败")
        return {**VALID_OUTPUT_DICT}

    async def close(self):
        pass


class TestIntegration:
    """集成测试：端到端调用插件。"""

    @pytest.mark.asyncio
    async def test_identify_basic(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
        )

        mock_ai = MockAIService()
        plugin = AIHazardIdentifier(mock_ai)

        output = await plugin.identify(make_input("防爆电箱堵头缺失"))
        assert output.hazard_type == HazardTypeEnum.UNSAFE_CONDITION
        assert output.hazard_level == HazardLevelEnum.MAJOR
        assert output.rectification_suggestion.corrective
        assert output.rectification_suggestion.preventive
        assert mock_ai.call_count == 1

    @pytest.mark.asyncio
    async def test_identify_uses_vision_when_photos_available(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
        )

        # Mock with vision support
        class VisionMockService(MockAIService):
            pass  # chat_vision_parsed already defined

        mock_ai = VisionMockService()
        mock_ai.chat_vision_parsed = mock_ai.chat_vision_parsed  # ensure available
        plugin = AIHazardIdentifier(mock_ai)

        output = await plugin.identify(make_input(
            "防爆电箱堵头缺失",
            defect_photos=["https://example.com/photo.jpg"],
        ))
        assert output.hazard_type == HazardTypeEnum.UNSAFE_CONDITION
        assert mock_ai.call_count == 1

    @pytest.mark.asyncio
    async def test_identify_ai_failure_raises(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
            IdentificationError,
        )

        mock_ai = MockAIService(fail=True)
        plugin = AIHazardIdentifier(mock_ai)

        with pytest.raises(IdentificationError):
            await plugin.identify(make_input("测试"))

    @pytest.mark.asyncio
    async def test_identify_batch(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
        )

        mock_ai = MockAIService()
        plugin = AIHazardIdentifier(mock_ai)

        inputs = [
            make_input("隐患1", hazard_no="HZ-001"),
            make_input("隐患2", hazard_no="HZ-002"),
            make_input("隐患3", hazard_no="HZ-003"),
        ]
        outputs = await plugin.identify_batch(inputs)
        assert len(outputs) == 3
        assert mock_ai.call_count == 3

    @pytest.mark.asyncio
    async def test_identify_validates_output_on_failure(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
            IdentificationError,
        )

        class BadAIService(MockAIService):
            async def chat_parsed(self, messages, expected_keys, temperature=0.1):
                return {"key_defect": "短"}  # 缺少其他字段

        mock_ai = BadAIService()
        plugin = AIHazardIdentifier(mock_ai)

        with pytest.raises((IdentificationError, KeyError)):
            await plugin.identify(make_input("测试"))

    @pytest.mark.asyncio
    async def test_prompt_includes_context(self):
        from app.modules.safety.ai_hazard_identification.plugin import (
            AIHazardIdentifier,
        )

        mock_ai = MockAIService()
        plugin = AIHazardIdentifier(mock_ai)

        await plugin.identify(make_input(
            "管道法兰泄漏",
            hazard_no="HZ-2026-0001",
            department="生产部",
            location="合成车间",
        ))

        # 检查 AI 收到的 prompt 包含所有上下文
        user_prompt = mock_ai.last_messages[1]["content"]
        assert "HZ-2026-0001" in user_prompt
        assert "管道法兰泄漏" in user_prompt
        assert "生产部" in user_prompt


# ═══════════════════════════════════════════════════════════════════════════
# 6. 质量验证：4 个标准示例的规则一致性
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityBenchmarks:
    """基于设计方案的 4 个标准示例验证规则一致性。"""

    def setup_method(self):
        self.engine = RuleEngine()

    def test_example1_electric_box(self):
        """示例1: 防爆电箱堵头 — 停产整改判断为最高优先级（无需断电可直接操作）。"""
        output = HazardIdentificationOutput(
            key_defect="现场防爆电箱一处备用引入口未使用防爆堵头封堵，箱体内部积尘严重，存在粉尘进入电箱引发短路或爆炸的风险",
            hazard_type=HazardTypeEnum.UNSAFE_CONDITION,
            hazard_category=HazardCategoryEnum.INSTRUMENT_ELECTRICAL,
            hazard_level=HazardLevelEnum.GENERAL,
            rectification_suggestion=RectificationSuggestion(
                corrective="对该电箱未封堵的引入口加装防爆堵头（安装堵头无需设备断电，可直接在线操作），使用防爆吸尘器清理箱内积尘，3个工作日内完成",
                preventive="修订防爆电气设备巡检制度，将引入口封堵状态纳入每周例行检查项，建立防爆设备全生命周期台账",
            ),
            major_hazard_basis="《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准》第十条：爆炸危险场所未按国家标准安装使用防爆电气设备；GB 3836.1-2010 第15章：电气设备引入装置的密封要求",
        )
        result = self.engine.validate(make_input("防爆电箱接线口未封堵"), output)
        assert result.is_valid, f"示例1验证失败: {result.errors}"

    def test_example2_height_work(self):
        """示例2: 高处作业未佩戴安全带。"""
        output = HazardIdentificationOutput(
            key_defect="作业人员在2.5m高的脚手架平台进行管道焊接作业，未佩戴安全带，且平台上未设置安全绳挂点，存在高处坠落风险",
            hazard_type=HazardTypeEnum.UNSAFE_ACTION,
            hazard_category=HazardCategoryEnum.VIOLATION_OPERATION,
            hazard_level=HazardLevelEnum.SERIOUS,
            rectification_suggestion=RectificationSuggestion(
                corrective="立即停止该作业人员的高处作业，监督其正确佩戴安全带并确认挂点牢固后方可继续作业；对当班全体作业人员进行高处作业安全专项培训，重点讲解安全带正确佩戴方法",
                preventive="在车间高处作业区域统一设置固定式安全绳挂点装置，纳入每日班前安全检查项；修订《高处作业安全管理规定》，明确安全带使用具体要求",
            ),
            major_hazard_basis="GB 30871-2022 第5.2条：高处作业人员应正确佩戴符合国家标准的安全带；《安全生产法》第四十五条",
        )
        result = self.engine.validate(make_input("高处作业未佩戴安全带"), output)
        assert result.is_valid, f"示例2验证失败: {result.errors}"

    def test_example3_blocked_fire_exit(self):
        """示例3: 消防通道堵塞。"""
        output = HazardIdentificationOutput(
            key_defect="车间南侧消防疏散通道堆放约30袋成品包装物料，通道有效通行宽度不足0.8m，应急疏散指示灯被物料遮挡",
            hazard_type=HazardTypeEnum.ENVIRONMENTAL,
            hazard_category=HazardCategoryEnum.EMERGENCY_MGMT,
            hazard_level=HazardLevelEnum.SERIOUS,
            rectification_suggestion=RectificationSuggestion(
                corrective="立即将通道上的30袋物料转移至指定物料暂存区，恢复通道畅通，确保净宽≥1.4m；在消防通道两侧地面施划黄色禁停标线，在墙面张贴'消防通道禁止堆放'警示标识",
                preventive="修订车间定置管理制度，明确消防疏散通道净宽≥1.4m的硬性指标，由安全员每月专项检查并拍照留档",
            ),
            major_hazard_basis="GB 50016-2014（2018年版）第7.3.1条：疏散通道的净宽度不应小于1.1m；《安全生产法》第四十二条",
        )
        result = self.engine.validate(make_input("消防通道堆放物料"), output)
        assert result.is_valid, f"示例3验证失败: {result.errors}"

    def test_example4_permit_issue(self):
        """示例4: 动火票证审批不完整。"""
        output = HazardIdentificationOutput(
            key_defect="一级动火作业票（编号DH-2026-0612）审批流程不完整：现场监护人、动火负责人签章栏均为空白",
            hazard_type=HazardTypeEnum.MANAGEMENT_DEFECT,
            hazard_category=HazardCategoryEnum.SPECIAL_OPERATION,
            hazard_level=HazardLevelEnum.GENERAL,
            rectification_suggestion=RectificationSuggestion(
                corrective="立即暂停该动火作业，要求现场监护人和动火负责人到场补签确认；组织涉及动火作业审批的相关人员进行作业票证规范填写专项培训",
                preventive="建立特殊作业票证三级审核制度，每周对已归档票证做10%随机抽查；检查结果纳入月度安全绩效考核",
            ),
            major_hazard_basis="GB 30871-2022 第4.7条：特殊作业审批手续应齐全；《安全生产法》第四十六条",
        )
        result = self.engine.validate(make_input("动火作业票证审批签章不完整"), output)
        assert result.is_valid, f"示例4验证失败: {result.errors}"
