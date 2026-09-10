"""Ticket 01 — 脚本4 优化1：控制措施按事故/行为推导（prompts + rules 改版）插件层测试。

覆盖（fake ai_service，无网络/真实 AI 依赖）：
- 输出含「针对事故N/行为N」依据标注 → 规则验证通过（无 error）
- 四类输出结构完整（engineering/management/ppe/emergency 均非空）
- BANNED 收窄后「应增加/需完善」类推导表述不再触发 error；「建议」仍触发 error
- 维度完全缺少依据标注 → 仅日志 warning、不阻断（strict_mode=True 下不抛 PluginError）
- FEWSHOT 示例：输入含人工已填 4 字段、输出通过规则验证

Bitable 流触发反转（_SCRIPT_REQUIRED_MODEL_KEYS[4] 改值）属优化2（ticket 02），不在此文件。
"""

from __future__ import annotations

import logging

import pytest

from app.modules.safety.ai_hazard_identification._base import PluginError
from app.modules.safety.ai_hazard_identification.script4_controls import prompts as p4
from app.modules.safety.ai_hazard_identification.script4_controls.plugin import (
    ControlMeasureExtractor,
)
from app.modules.safety.ai_hazard_identification.script4_controls.rules import (
    BANNED_IN_CONTROLS,
    ControlsRuleEngine,
)
from app.modules.safety.ai_hazard_identification.script4_controls.schemas import (
    ControlsInput,
    ControlsOutput,
)

# ── 带依据标注的标准输出（模仿 FEWSHOT 形态，无 BANNED 词）──
ANNOTATED_OUTPUT = {
    "engineering_controls": (
        "（1）反应罐R201配压力表（罐顶，0-1.6MPa）— 防止开盖超压（针对行为1：未确认罐压打开罐盖）\n"
        "（2）pH计在线监测（插入式，0-14）— 实时显示反应液pH（针对事故1：盐酸喷溅致化学灼伤）"
    ),
    "management_controls": (
        "（1）《反应岗位操作规程》（SOP-TL2-FY-001）— 规定开罐前确认罐压为0"
        "（针对行为1：未确认罐压打开罐盖）"
    ),
    "ppe": (
        "（1）防飞溅面屏（PC材质，EN166标准）— 开关罐盖和加酸时佩戴"
        "（针对事故1：盐酸喷溅致化学灼伤）"
    ),
    "emergency_measures": (
        "（1）洗眼器（复合式，反应罐R201东侧3m）— 应急冲洗"
        "（针对事故1：盐酸喷溅致化学灼伤）"
    ),
}

# ── 无依据标注的输出（触发软检查，仅日志告警）──
NO_BASIS_OUTPUT = {
    "engineering_controls": "（1）反应罐配压力表（罐顶）— 防止开盖超压\n（2）pH计在线监测 — 实时显示反应液pH",
    "management_controls": "（1）反应岗位操作规程 — 规定开罐前确认罐压为0",
    "ppe": "（1）防飞溅面屏 — 开关罐盖和加酸时佩戴",
    "emergency_measures": "（1）洗眼器 — 应急冲洗",
}


def make_input(**kwargs) -> ControlsInput:
    kwargs.setdefault("department", "提炼二部二车间")
    kwargs.setdefault("position", "反应岗位")
    kwargs.setdefault("production_step", "加盐酸调pH至4.5")
    kwargs.setdefault("specific_activity", "加盐酸调pH：泵入盐酸，氮气置换，搅拌监测pH")
    kwargs.setdefault("equipment_facilities", "反应罐R201、手推泵、氮气置换管线、pH计")
    kwargs.setdefault("raw_auxiliary_materials", "盐酸（30%，100L）、氮气")
    kwargs.setdefault("hazard_type", "腐蚀灼伤、化学灼伤")
    kwargs.setdefault("possible_accident", "盐酸喷溅致化学灼伤；氮气置换不彻底积聚可燃气体")
    kwargs.setdefault("unsafe_behavior", "未确认罐压打开罐盖")
    return ControlsInput(**kwargs)


def make_output(**overrides) -> ControlsOutput:
    return ControlsOutput(**{**ANNOTATED_OUTPUT, **overrides})


class _FakeAIService:
    """记录调用并返回预设 raw dict 的 fake ai_service（插件经 chat_parsed 消费）。"""

    def __init__(self, raw: dict):
        self.raw = raw
        self.calls: list[dict] = []

    async def chat_parsed(self, messages, expected_keys=None, temperature=None, max_tokens=None):
        self.calls.append(
            {"messages": messages, "expected_keys": expected_keys,
             "temperature": temperature, "max_tokens": max_tokens}
        )
        return self.raw


# ═══════════════════════════════════════════════════════════════════════════
# Prompt 改版断言
# ═══════════════════════════════════════════════════════════════════════════


class TestPromptsDerivation:
    """prompts.py 改版：角色反转 + 措施-风险对应 + 缺失覆盖检查。"""

    def test_system_role_is_derivation_expert(self):
        """角色从「识别已存在措施」翻转为「推导控制措施」。"""
        assert "风险控制措施推导专家" in p4.SYSTEM_ROLE
        assert "推导该岗位/步骤应具备的控制措施" in p4.SYSTEM_ROLE
        assert "识别当前岗位/步骤已实际存在的控制措施" not in p4.SYSTEM_ROLE

    def test_work_rules_require_basis_annotation(self):
        """每条措施必须注明（针对事故N/行为N：…）依据。"""
        assert "措施-风险对应" in p4.WORK_RULES
        assert "（针对事故N：" in p4.WORK_RULES
        assert "（针对行为N：" in p4.WORK_RULES
        assert "针对行为" in p4.WORK_RULES or "针对事故" in p4.WORK_RULES

    def test_work_rules_have_coverage_gap_check(self):
        """缺失覆盖检查：所有事故/行为至少一条对应措施。"""
        assert "缺失覆盖检查" in p4.WORK_RULES
        assert "覆盖缺口" in p4.WORK_RULES

    def test_work_rules_keep_four_categories(self):
        """四类归档结构保留。"""
        for section in ("工程控制", "管理控制", "个人防护", "应急措施"):
            assert section in p4.WORK_RULES
        assert "待人工确认" in p4.WORK_RULES

    def test_output_format_keeps_required_points(self):
        """5 个关键【输出格式要求】子串保留（test_script_prompt_format 兼容）。"""
        required_points = [
            "各输出字段均需按条目分点、分行生成",
            "每条检查项单独成行，使用中文序号格式编号",
            "编号格式统一为：（1）……（2）……（3）……",
            "等其他编号格式",
            "不要将多条检查项合并在同一行输出",
        ]
        assert "【输出格式要求】" in p4.OUTPUT_FORMAT
        for point in required_points:
            assert point in p4.OUTPUT_FORMAT, f"OUTPUT_FORMAT 缺少规范「{point}」"
        # 依据标注要求进入输出格式
        assert "（针对事故N/行为N" in p4.OUTPUT_FORMAT

    def test_fewshot_input_includes_manual_measures(self):
        """FEWSHOT 示例输入包含人工已填的 4 类控制措施（人工先填 → AI 润色）。"""
        ex = p4.FEWSHOT_EXAMPLES[0]
        for key in (
            "existing_engineering_controls",
            "existing_management_controls",
            "existing_ppe",
            "existing_emergency_measures",
        ):
            assert key in ex["input"], f"FEWSHOT 输入缺少人工字段 {key}"

    def test_fewshot_output_contains_basis_annotations(self):
        """FEWSHOT 示例输出每条措施带依据标注。"""
        ex = p4.FEWSHOT_EXAMPLES[0]
        for label, value in ex["output"].items():
            assert "（针对" in value, f"FEWSHOT {label} 缺少依据标注"
            assert ("针对事故" in value or "针对行为" in value), f"FEWSHOT {label} 缺少依据标注"

    def test_fewshot_output_passes_validation(self):
        """FEWSHOT 示例输出必须通过规则验证（模型模仿的强先验）。"""
        engine = ControlsRuleEngine()
        errors = engine.validate(
            make_input(), ControlsOutput(**p4.FEWSHOT_EXAMPLES[0]["output"])
        )
        assert errors == [], f"FEWSHOT 示例输出未通过验证: {errors}"

    def test_banned_words_narrowed(self):
        """BANNED 收窄：去掉「应增加/需完善」族，保留空泛含糊词。"""
        assert "应增加" not in BANNED_IN_CONTROLS
        assert "需完善" not in BANNED_IN_CONTROLS
        assert "需要补充" not in BANNED_IN_CONTROLS
        for phrase in ("建议", "推荐", "可考虑", "宜", "最好"):
            assert phrase in BANNED_IN_CONTROLS


# ═══════════════════════════════════════════════════════════════════════════
# 规则引擎行为
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleEngineDerivation:
    """rules.py 改版：BANNED 收窄 + 依据软校验。"""

    def setup_method(self):
        self.engine = ControlsRuleEngine()

    def test_derivation_wording_not_error(self):
        """含「应增加/需完善」的推导类表述不再触发 error。"""
        output = make_output(
            engineering_controls=(
                "（1）应增加事故通风系统（全面通风）— 及时排出可燃气体"
                "（针对事故1：盐酸喷溅致化学灼伤）"
            ),
            management_controls=(
                "（1）需完善岗位巡检制度（每2小时一次）— 检查压力/温度"
                "（针对事故2：氮气置换不彻底积聚可燃气体）"
            ),
        )
        errors = self.engine.validate(make_input(), output)
        assert errors == []

    def test_ban_phrase_still_error(self):
        """含「建议」的空泛表述仍触发 error。"""
        output = make_output(
            engineering_controls="（1）建议增加通风系统（全面通风）— 及时排出可燃气体"
        )
        errors = self.engine.validate(make_input(), output)
        assert any("建议" in e for e in errors)
        assert any("空泛/含糊" in e for e in errors)

    def test_annotated_output_passes(self):
        """带（针对事故/行为）依据标注的四类输出通过验证。"""
        errors = self.engine.validate(make_input(), make_output())
        assert errors == []

    def test_missing_basis_logs_warning_not_error(self, caplog):
        """维度完全无依据标注 → 仅日志 warning，不返回 error。"""
        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.safety.ai_hazard_identification.script4_controls.rules",
        ):
            errors = self.engine.validate(make_input(), ControlsOutput(**NO_BASIS_OUTPUT))
        assert errors == []
        assert any("依据标注" in r.message for r in caplog.records)

    def test_partial_basis_annotation_no_warning(self, caplog):
        """部分维度含依据标注时不告警（字段级宽松判定）。"""
        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.safety.ai_hazard_identification.script4_controls.rules",
        ):
            errors = self.engine.validate(make_input(), make_output())
        assert errors == []
        assert not any("依据标注" in r.message for r in caplog.records)

    def test_existing_validations_kept(self):
        """保留既有校验：四维度全待确认 / 过短 / PPE 含工程描述。"""
        # 四维度全「待人工确认」
        errors = self.engine.validate(
            make_input(),
            ControlsOutput(
                engineering_controls="待人工确认",
                management_controls="待人工确认",
                ppe="待人工确认",
                emergency_measures="待人工确认",
            ),
        )
        assert any("四个维度不能全部" in e for e in errors)
        # 过短
        errors = self.engine.validate(
            make_input(),
            make_output(engineering_controls="通风"),
        )
        assert any("过短" in e for e in errors)
        # PPE 含工程描述
        errors = self.engine.validate(
            make_input(),
            make_output(ppe="（1）防飞溅面屏 — 佩戴（针对事故1：…）\n（2）安全阀（针对事故1：…）"),
        )
        assert any("PPE 维度不应包含工程控制描述" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# 插件集成（fake ai_service）
# ═══════════════════════════════════════════════════════════════════════════


class TestPluginIntegration:
    """ControlMeasureExtractor 端到端（fake ai_service，strict_mode 默认 True）。"""

    async def test_identify_output_contains_basis_annotation(self):
        """fake ai_service 输出含依据标注、四类结构完整 → identify 成功。"""
        ai = _FakeAIService(ANNOTATED_OUTPUT)
        plugin = ControlMeasureExtractor(ai)
        out = await plugin.identify(make_input())
        assert "（针对行为1：未确认罐压打开罐盖）" in out.engineering_controls
        assert "（针对事故1：盐酸喷溅致化学灼伤）" in out.ppe
        # 四类结构完整且非空
        for value in (
            out.engineering_controls,
            out.management_controls,
            out.ppe,
            out.emergency_measures,
        ):
            assert value and value.strip() != "待人工确认"
        # prompt 结构：system 角色 + user prompt 含工作规则
        assert ai.calls[0]["messages"][0]["role"] == "system"
        user_prompt = ai.calls[0]["messages"][1]["content"]
        assert "措施-风险对应" in user_prompt
        assert "（针对事故N：" in user_prompt
        assert ai.calls[0]["temperature"] == 0.05

    async def test_identify_allows_derivation_wording(self):
        """输出含「应增加」推导表述 → strict_mode=True 下不抛 PluginError。"""
        ai = _FakeAIService(
            {
                **ANNOTATED_OUTPUT,
                "engineering_controls": (
                    "（1）应增加事故通风系统（全面通风）— 及时排出可燃气体"
                    "（针对事故2：氮气置换不彻底积聚可燃气体）"
                ),
            }
        )
        plugin = ControlMeasureExtractor(ai)
        out = await plugin.identify(make_input())
        assert "应增加事故通风系统" in out.engineering_controls

    async def test_identify_ban_phrase_raises_in_strict_mode(self):
        """输出含「建议」→ strict_mode 默认 True → PluginError。"""
        ai = _FakeAIService(
            {
                **ANNOTATED_OUTPUT,
                "engineering_controls": "（1）建议增加通风系统（全面通风）— 及时排出可燃气体",
            }
        )
        plugin = ControlMeasureExtractor(ai)
        with pytest.raises(PluginError, match="空泛/含糊"):
            await plugin.identify(make_input())

    async def test_identify_missing_basis_warns_but_succeeds(self, caplog):
        """输出四类全无依据标注 → 不抛异常，仅日志 warning（软校验不阻断）。"""
        ai = _FakeAIService(NO_BASIS_OUTPUT)
        plugin = ControlMeasureExtractor(ai)
        with caplog.at_level(
            logging.WARNING,
            logger="app.modules.safety.ai_hazard_identification.script4_controls.rules",
        ):
            out = await plugin.identify(make_input())
        assert out is not None
        assert any("依据标注" in r.message for r in caplog.records)

    async def test_auto_correct_fills_empty_with_unconfirmed(self):
        """auto_correct 不变：空值填「待人工确认」。"""
        ai = _FakeAIService({**ANNOTATED_OUTPUT, "emergency_measures": "  "})
        plugin = ControlMeasureExtractor(ai)
        out = await plugin.identify(make_input())
        assert out.emergency_measures == "待人工确认"
