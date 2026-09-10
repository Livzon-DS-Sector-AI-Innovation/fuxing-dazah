"""脚本8 排查内容生成 Plugin — 独立测试套件。

不依赖数据库、飞书或 FastAPI，仅测试脚本8插件核心逻辑。
运行: uv run pytest app/modules/safety/ai_hazard_identification/tests/test_script8_inspection.py -v
"""

from __future__ import annotations

import pytest

from app.modules.safety.ai_hazard_identification._base import PluginError
from app.modules.safety.ai_hazard_identification.script8_inspection_items.plugin import (
    InspectionItemGenerator,
)
from app.modules.safety.ai_hazard_identification.script8_inspection_items.rules import (
    InspectionRuleEngine,
    auto_correct,
    count_numbered_items,
    is_empty_input,
)
from app.modules.safety.ai_hazard_identification.script8_inspection_items.schemas import (
    InspectionItemsInput,
    InspectionItemsOutput,
)

# ═══════════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════════

VALID_INPUT_DICT = {
    "engineering_controls": "通风系统、静电接地、气体检测报警",
    "management_controls": "安全操作规程、交接班记录、特殊作业票证",
    "ppe": "防化服、防毒面具、防护面屏",
    "emergency_measures": "应急物资、洗眼器、应急疏散通道",
}

VALID_OUTPUT_DICT = {
    "engineering_items": (
        "（1）检查通风系统是否开启并正常运行，排风口是否畅通。\n"
        "（2）检查静电接地连接是否完好，接地标识是否清晰。\n"
        "（3）检查气体检测报警器是否在线运行，报警值设置是否符合要求。"
    ),
    "management_items": (
        "（1）检查岗位安全操作规程是否现场可获取。\n"
        "（2）检查交接班记录是否完整填写。\n"
        "（3）检查特殊作业票证审批手续是否齐全。"
    ),
    "ppe_items": (
        "（1）检查防化服是否完好无破损。\n"
        "（2）检查防毒面具是否在有效期内。\n"
        "（3）检查防护面屏佩戴是否规范。"
    ),
    "emergency_items": (
        "（1）检查应急物资是否按清单配置齐全。\n"
        "（2）检查洗眼器出水是否正常。\n"
        "（3）检查应急疏散通道是否畅通。"
    ),
}


def make_input(**kwargs) -> InspectionItemsInput:
    data = {**VALID_INPUT_DICT, **kwargs}
    return InspectionItemsInput(**data)


def make_output(**overrides) -> InspectionItemsOutput:
    data = {**VALID_OUTPUT_DICT, **overrides}
    return InspectionItemsOutput(**data)


class MockAIService:
    """Mock AI 服务，返回固定的标准输出。"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0
        self.last_messages = None

    async def chat_parsed(self, messages, expected_keys, temperature=0.1, max_tokens=None):
        self.call_count += 1
        self.last_messages = messages
        if self.fail:
            raise Exception("模拟 AI 调用失败")
        return {**VALID_OUTPUT_DICT}

    async def close(self):
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. Schema 测试
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemas:
    """输入/输出数据模型验证。"""

    def test_input_full(self):
        inp = make_input()
        assert inp.engineering_controls == VALID_INPUT_DICT["engineering_controls"]
        assert inp.emergency_measures == VALID_INPUT_DICT["emergency_measures"]

    def test_input_empty_allowed(self):
        inp = make_input(engineering_controls="", management_controls="", ppe="", emergency_measures="")
        assert inp.engineering_controls == ""
        assert inp.ppe == ""

    def test_output_from_valid_dict(self):
        output = make_output()
        assert output.engineering_items.startswith("（1）检查")
        assert output.emergency_items.count("检查") >= 3

    def test_output_requires_all_fields(self):
        with pytest.raises(ValueError):
            InspectionItemsOutput(**{k: v for k, v in VALID_OUTPUT_DICT.items() if k != "ppe_items"})


# ═══════════════════════════════════════════════════════════════════════════
# 2. 规则引擎测试
# ═══════════════════════════════════════════════════════════════════════════


class TestInspectionRuleEngine:
    """脚本8 输出规则验证。"""

    def setup_method(self):
        self.engine = InspectionRuleEngine()

    def test_valid_output_passes(self):
        errors = self.engine.validate(make_input(), make_output())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_empty_input_field_requires_no(self):
        """规则9：输入为空 → 对应输出必须为「无」。"""
        inp = make_input(engineering_controls="")
        out = make_output(engineering_items="无")
        errors = self.engine.validate(inp, out)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_nonempty_input_with_no_is_error(self):
        """输入非空但输出为「无」→ 错误（规则9反例）。"""
        inp = make_input(engineering_controls="通风系统")
        out = make_output(engineering_items="无")
        errors = self.engine.validate(inp, out)
        assert any("无" in e and "工程" in e for e in errors)

    def test_unfilled_input_phrase_treated_empty(self):
        """「未填写」/「无相关措施」等输入视同为空。"""
        for phrase in ("无", "未填写", "无相关措施"):
            inp = make_input(engineering_controls=phrase)
            out = make_output(engineering_items="无")
            errors = self.engine.validate(inp, out)
            assert errors == [], f"phrase={phrase}: {errors}"

    def test_line_must_start_with_check(self):
        """规则4：每条检查项必须以「检查」开头。"""
        out = make_output(engineering_items="（1）确认通风系统是否开启。\n（2）检查排风口。")
        errors = self.engine.validate(make_input(), out)
        assert any("检查" in e and "开头" in e for e in errors)

    def test_wrong_numbering_rejected(self):
        """格式：禁止使用 1./一、/- 等其他编号。"""
        for bad in ("1.检查通风系统。", "一、检查通风系统。", "- 检查通风系统。"):
            out = make_output(engineering_items=f"{bad}\n（2）检查排风口。\n（3）检查报警器。")
            errors = self.engine.validate(make_input(), out)
            assert any("编号" in e for e in errors), f"bad={bad}: {errors}"

    def test_banned_remediation_phrase_rejected(self):
        """禁止新增/整改式表述：建议、应当、需要、加强、完善、增设、建立、配备。"""
        for phrase in ("建议", "加强", "应当", "需要", "完善", "增设", "建立", "配备"):
            out = make_output(engineering_items=f"（1）检查通风系统运行状态，{phrase}定期维护。\n（2）检查排风口畅通。\n（3）检查报警器在线。")
            errors = self.engine.validate(make_input(), out)
            assert any("整改式表述" in e and phrase in e for e in errors), f"phrase={phrase}: {errors}"

    def test_check_question_usage_allowed(self):
        """允许「检查…是否配备到位/是否需要」等合规核查问句（非整改建议）。"""
        out = make_output(
            engineering_items=(
                "（1）检查通风系统是否开启并正常运行。\n"
                "（2）检查消防设施是否配备到位。\n"
                "（3）检查气体检测报警器是否需要重新校准。"
            )
        )
        errors = self.engine.validate(make_input(), out)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_concatenated_single_line_counts_items(self):
        """单行拼接输出（多条（N）合并到一行）应按（N）编号计数而非按行数。"""
        out = make_output(
            engineering_items=(
                "（1）检查通风系统是否开启并正常运行。"
                "（2）检查静电接地连接是否完好。"
                "（3）检查气体检测报警器是否在线运行。"
            )
        )
        errors = self.engine.validate(make_input(), out)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_remediation_outside_check_question_rejected(self):
        """整改式语句（不在核查问句语境）仍被拦截。"""
        for phrase in ("应配备", "建议增设", "必须增加", "有待加强"):
            out = make_output(
                engineering_items=f"（1）检查通风系统运行状态。\n（2）{phrase}防毒面具。\n（3）检查报警器在线。"
            )
            errors = self.engine.validate(make_input(), out)
            assert any("整改式表述" in e for e in errors), f"phrase={phrase}: {errors}"

    def test_fewer_than_3_items_rejected(self):
        """规则10：每个输出字段建议 3-10 条。"""
        out = make_output(engineering_items="（1）检查通风系统是否开启。\n（2）检查排风口是否畅通。")
        errors = self.engine.validate(make_input(), out)
        assert any("至少" in e for e in errors)

    def test_ppe_field_no_engineering_keywords(self):
        """不混写：个人防护排查内容不应含工程类描述。"""
        out = make_output(ppe_items="（1）检查联锁装置是否正常。\n（2）检查防护面屏完好。\n（3）检查防毒面具有效期。")
        errors = self.engine.validate(make_input(), out)
        assert any("工程" in e and "个人防护" in e for e in errors)

    def test_count_numbered_items(self):
        assert count_numbered_items("（1）检查A\n（2）检查B\n（3）检查C") == 3
        assert count_numbered_items("无") == 0
        assert count_numbered_items("") == 0

    def test_is_empty_input(self):
        assert is_empty_input("")
        assert is_empty_input("无")
        assert is_empty_input("未填写")
        assert is_empty_input("无相关措施")
        assert not is_empty_input("通风系统")


# ═══════════════════════════════════════════════════════════════════════════
# 3. 自动修正测试
# ═══════════════════════════════════════════════════════════════════════════


class TestAutoCorrect:
    """自动修正功能测试。"""

    def test_strips_output(self):
        out = make_output(engineering_items="  （1）检查通风系统。\n（2）检查排风口。  ")
        corrected = auto_correct(out, make_input())
        assert corrected.engineering_items == "（1）检查通风系统。\n（2）检查排风口。"

    def test_empty_input_fills_no(self):
        """输入为空 → 对应输出自动填「无」。"""
        out = make_output()  # AI 返回了内容，但输入为空
        corrected = auto_correct(out, make_input(engineering_controls=""))
        assert corrected.engineering_items == "无"
        # 其余字段保留
        assert corrected.management_items != "无"

    def test_empty_output_with_nonempty_input_keeps_unconfirmed(self):
        out = make_output(engineering_items="")
        corrected = auto_correct(out, make_input())
        assert corrected.engineering_items == "待人工确认"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 集成测试（Mock AI Service）
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """端到端调用脚本8插件。"""

    @pytest.mark.asyncio
    async def test_identify_basic(self):
        mock_ai = MockAIService()
        plugin = InspectionItemGenerator(mock_ai)

        output = await plugin.identify(make_input())
        assert output.engineering_items == VALID_OUTPUT_DICT["engineering_items"]
        assert output.emergency_items == VALID_OUTPUT_DICT["emergency_items"]
        assert mock_ai.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_input_outputs_all_no(self):
        mock_ai = MockAIService()
        plugin = InspectionItemGenerator(mock_ai)

        inp = make_input(engineering_controls="", management_controls="", ppe="", emergency_measures="")
        output = await plugin.identify(inp)
        assert output.engineering_items == "无"
        assert output.management_items == "无"
        assert output.ppe_items == "无"
        assert output.emergency_items == "无"

    @pytest.mark.asyncio
    async def test_partial_empty_input(self):
        mock_ai = MockAIService()
        plugin = InspectionItemGenerator(mock_ai)

        inp = make_input(engineering_controls="", management_controls="安全操作规程")
        output = await plugin.identify(inp)
        # 输入为空的字段 → 无；输入非空的字段 → 保留 AI 输出
        assert output.engineering_items == "无"
        assert output.management_items == VALID_OUTPUT_DICT["management_items"]

    @pytest.mark.asyncio
    async def test_ai_failure_raises(self):
        mock_ai = MockAIService(fail=True)
        plugin = InspectionItemGenerator(mock_ai)

        with pytest.raises(PluginError):
            await plugin.identify(make_input())

    @pytest.mark.asyncio
    async def test_prompt_includes_input(self):
        mock_ai = MockAIService()
        plugin = InspectionItemGenerator(mock_ai)

        await plugin.identify(make_input())
        user_prompt = mock_ai.last_messages[1]["content"]
        assert "通风系统" in user_prompt
        assert "安全操作规程" in user_prompt
        assert "现有工程控制措施" in user_prompt
