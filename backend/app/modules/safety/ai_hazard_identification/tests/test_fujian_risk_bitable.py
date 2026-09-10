"""Ticket 02 — 脚本3.5 福建固有风险评级 Bitable 流接入测试。

覆盖（spec.md 测试决策 / backend-design.md §6）：
- advance_record 脚本3 成功后触发脚本3.5 并回写「固有风险等级（福建AI）」
- 脚本3.5 失败不阻断脚本3 LEC 回写（失败降级）
- 幂等：福建字段已回填则不重跑脚本3.5
- operator_count int 转换（str/float/int/空/缺失，防 _text 转字符串）
- 3.5 输出 risk_label 为 None → 不回写
- 回写白名单：脚本3.5 字段自动纳入 _ALLOWED_AI_FIELDS（map_ai_output_to_bitable 校验）
- 非脚本3 不触发脚本3.5

复用 test_bitable_service.py 的 _RecordingRunner / _ready_fields 范式，
注入 fake run_script，无真实 AI 调用、无真实 Bitable。
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.modules.safety.ai_hazard_identification.tests.test_bitable_service import (
    _OUTPUTS,
    _ready_fields,
    _RecordingRunner,
)
from app.modules.safety.service.hazard_identification_bitable import (
    _ALLOWED_AI_FIELDS,
    _FUJIAN_RISK_FIELD,
    HazardIdentificationBitableService,
    map_bitable_to_model,
)


# 脚本3.5 输出：七指标 + risk_label（fake，仅验证编排，不真实调 AI）。
# 与 ticket 01 FujianRiskOutput 字段形状一致；reasoning 不落库、不回写。
def _fj_output(risk_label: str | None = "较大风险") -> SimpleNamespace:
    return SimpleNamespace(
        substance="一般风险", layout=None, environment=None,
        process="较大风险", pressure=None, temperature=None,
        personnel_level="一般风险",
        risk_label=risk_label,
        reasoning="测试推理（不落库）",
    )


def _runner_with_fj(risk_label: str | None = "较大风险") -> _RecordingRunner:
    """在既有 1..8 输出上补 3.5 输出的 fake runner。"""
    outputs = dict(_OUTPUTS)
    outputs[3.5] = _fj_output(risk_label)
    return _RecordingRunner(outputs)


class TestScript35Trigger:
    """脚本3 执行成功后触发脚本3.5 并回写「固有风险等级（福建AI）」。"""

    async def test_script3_success_triggers_3_5_and_writes_back(self):
        runner = _runner_with_fj("较大风险")
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(3))
        # 脚本3 LEC 回写不受影响
        assert out["可能性L（固有）（AI）"] == 3
        assert out["暴露频率E（固有）（AI）"] == 6
        assert out["严重性C（固有）（AI）"] == 15
        # 脚本3.5 附属回写（多选字段 → list[选项名]）
        assert out[_FUJIAN_RISK_FIELD] == ["较大风险"]
        # 调用序列：先脚本3 后脚本3.5（附属，不进状态机）
        assert [c[0] for c in runner.calls] == [3, 3.5]
        # 3.5 复用脚本3 的 effective 输入 dict
        assert runner.calls[1][1] == runner.calls[0][1]

    async def test_3_5_failure_does_not_block_script3_writeback(self):
        """脚本3.5 失败（runner 返回 None）→ 不阻断脚本3 LEC 回写。"""
        outputs = dict(_OUTPUTS)
        outputs[3.5] = None
        runner = _RecordingRunner(outputs)
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(3))
        assert out["可能性L（固有）（AI）"] == 3
        assert out["暴露频率E（固有）（AI）"] == 6
        assert out["严重性C（固有）（AI）"] == 15
        assert _FUJIAN_RISK_FIELD not in out
        assert [c[0] for c in runner.calls] == [3, 3.5]  # 3.5 被尝试但失败

    async def test_3_5_idempotent_when_field_already_present(self):
        """「固有风险等级（福建AI）」已回填 → 不重跑脚本3.5（_ai_output_present 幂等）。"""
        fields = _ready_fields(3)
        fields[_FUJIAN_RISK_FIELD] = "重大风险"
        runner = _runner_with_fj("较大风险")
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["可能性L（固有）（AI）"] == 3  # 脚本3 照常回写
        assert _FUJIAN_RISK_FIELD not in out      # 不重写已回填的福建字段
        assert [c[0] for c in runner.calls] == [3]  # 3.5 未被调用

    async def test_3_5_risk_label_none_not_written(self):
        """3.5 输出 risk_label 为 None（信息不足）→ 不回写该字段。"""
        runner = _runner_with_fj(risk_label=None)
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(3))
        assert out["可能性L（固有）（AI）"] == 3
        assert _FUJIAN_RISK_FIELD not in out
        assert [c[0] for c in runner.calls] == [3, 3.5]

    async def test_non_script3_does_not_trigger_3_5(self):
        """非脚本3（如 target==2）不触发脚本3.5（target==3 守卫）。"""
        runner = _runner_with_fj("较大风险")
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(2))
        assert out["危险类型（AI）"] == ["设备设施缺陷"]
        assert [c[0] for c in runner.calls] == [2]


class TestOperatorCountMapping:
    """操作人数（人工）→ operator_count int 转换（_effective_int，防 _text 转字符串）。"""

    def test_map_bitable_to_model_int_forms(self):
        cases = [
            ("5", 5),     # Bitable 文本形态
            (5.0, 5),     # Bitable 数值 float
            (5, 5),       # Bitable 数值 int
            ("5.0", 5),   # 数字字符串容忍
            ("", None),   # 空字符串 → None
            (None, None),  # 显式 None → None
        ]
        for raw, expected in cases:
            fields = {"操作人数（人工）": raw}
            model = map_bitable_to_model(fields)
            assert model["operator_count"] == expected, f"{raw!r} → {expected!r}"
            if expected is not None:
                assert isinstance(model["operator_count"], int), "必须是 int，不能是 str"

    async def test_effective_passes_int_to_runner(self):
        """advance_record 中 effective 的 operator_count 为 int（脚本3 与脚本3.5 共享）。"""
        fields = _ready_fields(3)
        fields["操作人数（人工）"] = "5"
        runner = _runner_with_fj("较大风险")
        svc = HazardIdentificationBitableService(run_script=runner)
        await svc.advance_record(fields)
        assert [c[0] for c in runner.calls] == [3, 3.5]
        for _, effective in runner.calls:
            assert isinstance(effective["operator_count"], int)
            assert effective["operator_count"] == 5

    async def test_operator_count_missing_is_none(self):
        """操作人数缺失：map_bitable_to_model 不报错（None），3.5 仍能触发（AI 保守推断）。"""
        fields = _ready_fields(3)  # 无「操作人数（人工）」字段
        model = map_bitable_to_model(fields)
        assert "operator_count" in model
        assert model["operator_count"] is None
        runner = _runner_with_fj("较大风险")
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out[_FUJIAN_RISK_FIELD] == ["较大风险"]
        assert [c[0] for c in runner.calls] == [3, 3.5]
        assert runner.calls[0][1]["operator_count"] is None
        assert runner.calls[1][1]["operator_count"] is None


class TestWritebackWhitelist:
    """脚本3.5 回写字段自动纳入 _ALLOWED_AI_FIELDS 白名单（map_ai_output_to_bitable 校验）。"""

    def test_fujian_field_in_allowed_ai_fields(self):
        assert _FUJIAN_RISK_FIELD in _ALLOWED_AI_FIELDS

    def test_map_3_5_respects_whitelist(self):
        svc = HazardIdentificationBitableService()
        out = svc.map_ai_output_to_bitable(3.5, _fj_output("较大风险"))
        # 「固有风险等级（福建AI）」是多选字段(type=4)，回写值必须是 list[选项名]
        assert out == {_FUJIAN_RISK_FIELD: ["较大风险"]}
        # 白名单外字段一律抛 ValueError（程序错误兜底）
        with patch.dict(
            "app.modules.safety.service.hazard_identification_bitable._OUTPUT_FIELDS",
            {99: {"phantom_attr": "越界字段（AI）"}},
        ):
            try:
                svc.map_ai_output_to_bitable(99, SimpleNamespace(phantom_attr="x"))
                raise AssertionError("白名单外回写应抛 ValueError")
            except ValueError:
                pass


class TestMirrorMapping:
    """Bitable→平台镜像映射：福建等级列 → inherent_risk_level_fj（WARN 修复回归）。"""

    def test_mirror_fj_field_to_model(self):
        """「固有风险等级（福建AI）」回填后，map_bitable_to_model 应同步到平台镜像列。"""
        fields = _ready_fields(3)
        fields[_FUJIAN_RISK_FIELD] = "重大风险"
        model = map_bitable_to_model(fields)
        assert model["inherent_risk_level_fj"] == "重大风险"

    def test_mirror_fj_field_missing_is_none(self):
        """Bitable 无福建字段值 → 平台镜像列 None（键完整，可落 NULL）。"""
        fields = _ready_fields(3)
        model = map_bitable_to_model(fields)
        assert "inherent_risk_level_fj" in model
        assert model["inherent_risk_level_fj"] is None
