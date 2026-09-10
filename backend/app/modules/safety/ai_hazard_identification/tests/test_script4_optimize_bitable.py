"""Ticket 02 — 优化2：脚本4 人工先填 + AI 润色（Bitable 流触发反转 + AI 优先语义）测试。

覆盖（ticket 02 / backend-design.md §3、R-1、R-2）：
- 4 类人工措施非空才触发脚本4；任一/全部为空 → 阻塞（noop）
- AI 润色只回写（AI）字段，绝不写（人工）字段（平台硬边界）
- effective 注入人工原文（AI 运行前 AI 字段空 → AI 优先回退取人工）
- AI 润色已回写后幂等不重跑
- 脚本4 审核通过 → 推进脚本5 并续跑
- 脚本5 输入读到 AI 润色稿（AI 优先：人工原文 + AI 润色稿并存 → 取 AI 值）
- 脚本8 仍读人工原文（_build_script_input(8) 走 _SCRIPT8_MANUAL_MEASURES 不变）
- 脚本3.5 回归（_ready_fields(3) 不受触发反转影响）
- map_bitable_to_model：脚本4 四键 AI 优先 + 其余脚本人工优先不受影响

复用 test_bitable_service.py 的 _RecordingRunner / _ready_fields 范式，
注入 fake run_script，无 DB/无网络/无真实 AI。
"""

from types import SimpleNamespace

from app.modules.safety.ai_hazard_identification.tests.test_bitable_service import (
    _OUTPUTS,
    _SCRIPT_AI_OUTPUTS,
    NODES,
    _boundary_ok,
    _ready_fields,
    _RecordingRunner,
)
from app.modules.safety.service.hazard_identification_bitable import (
    _FUJIAN_RISK_FIELD,
    HazardIdentificationBitableService,
    map_bitable_to_model,
)

# 脚本4 AI 润色稿（区别于人工原文，验证回写/取值语义用）
_POLISHED_4 = SimpleNamespace(
    engineering_controls="通风系统（全面通风，风机2台）— 稀释可燃蒸气（针对事故2：…）",
    management_controls="安全操作规程（SOP-001）— 开盖前确认罐压（针对行为1：…）",
    ppe="防护面屏（PC材质）— 加酸时佩戴（针对事故1：…）",
    emergency_measures="应急物资（洗眼器/灭火器）— 灼伤应急（针对事故1：…）",
)

# 4 类人工字段（_ready_fields(4) 注入的样本值，与脚本8 分支同值）
_MANUAL_FIELDS = {
    "现有工程控制措施（人工）": "通风系统", "现有管理控制措施（人工）": "安全操作规程",
    "现有个人防护措施（人工）": "防护面屏", "现有应急措施（人工）": "应急物资",
}


def _runner4() -> _RecordingRunner:
    """在既有 1..8 输出上把脚本4 换成 AI 润色稿的 fake runner。"""
    outputs = dict(_OUTPUTS)
    outputs[4] = _POLISHED_4
    return _RecordingRunner(outputs)


class TestScript4Trigger:
    """触发反转：4 类人工措施非空才触发脚本4（AI 润色回写（AI）字段）。"""

    async def test_runs_when_manual_fields_filled(self):
        runner = _runner4()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(4))
        assert out["现有工程控制措施（AI）"] == _POLISHED_4.engineering_controls
        assert out["现有管理控制措施（AI）"] == _POLISHED_4.management_controls
        assert out["现有个人防护措施（AI）"] == _POLISHED_4.ppe
        assert out["现有应急措施（AI）"] == _POLISHED_4.emergency_measures
        assert "AI流程节点进度" not in out  # RUN 不推进节点（审核驱动）
        assert runner.calls[0][0] == 4

    def test_blocked_when_any_manual_empty(self):
        svc = HazardIdentificationBitableService()
        for fname in _MANUAL_FIELDS:
            fields = _ready_fields(4)
            fields[fname] = ""
            assert svc.decide_next_script(fields) is None, f"{fname} 为空应阻塞脚本4"

    async def test_blocked_noop_when_all_manual_empty(self):
        fields = _ready_fields(4)
        for fname in _MANUAL_FIELDS:
            fields.pop(fname, None)
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) is None
        runner = _RecordingRunner()
        svc2 = HazardIdentificationBitableService(run_script=runner)
        out = await svc2.advance_record(fields)
        assert out is None
        assert runner.calls == []

    async def test_effective_injects_manual_original(self):
        """AI 运行前 effective 的 existing_* = 人工原文（AI 字段空 → AI 优先回退取人工）。"""
        runner = _runner4()
        svc = HazardIdentificationBitableService(run_script=runner)
        await svc.advance_record(_ready_fields(4))
        effective = runner.calls[0][1]
        assert effective["existing_engineering_controls"] == "通风系统"
        assert effective["existing_management_controls"] == "安全操作规程"
        assert effective["existing_ppe"] == "防护面屏"
        assert effective["existing_emergency_measures"] == "应急物资"

    async def test_polish_writes_only_ai_fields(self):
        """AI 润色只回写（AI）字段，绝不写（人工）字段（平台硬边界）。"""
        runner = _runner4()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(4))
        assert _boundary_ok(out)
        assert "现有工程控制措施（人工）" not in out

    async def test_idempotent_after_ai_run(self):
        """AI 润色已回写（4 个（AI）字段非空）→ 再次 advance_record 不重跑脚本4。"""
        fields = _ready_fields(4)
        fields.update(_SCRIPT_AI_OUTPUTS[4])
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out is None
        assert runner.calls == []


class TestScript4Advance:
    """审核驱动推进：脚本4 审核通过 → 推进脚本5 并续跑。"""

    async def test_approved_advances_and_runs_script5(self):
        fields = _ready_fields(4)
        fields.update(_SCRIPT_AI_OUTPUTS[4])   # AI 润色稿已回写
        fields["脚本4（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[5]
        assert runner.calls[0][0] == 5
        assert out["可能性L(残余）（AI）"] == 1

    async def test_manual_filled_approved_without_ai_advances_past(self):
        """固化现状语义（设计文档 R-3）：人工已填+已审核但 AI 未跑 → 视为完成推进脚本5、不重跑脚本4。"""
        fields = _ready_fields(4)
        fields["脚本4（人工审核状态）"] = "已审核"   # 人工已填、AI 字段仍空
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[5]
        assert runner.calls[0][0] == 5

    async def test_not_approved_after_ai_run_waits(self):
        """AI 润色已回写但未审核 → 等审（不推进、不重跑）。"""
        fields = _ready_fields(4)
        fields.update(_SCRIPT_AI_OUTPUTS[4])
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out is None
        assert runner.calls == []


class TestAIPrioritySemantics:
    """AI 优先：脚本5 输入读到 AI 润色稿；脚本8 仍读人工原文；其余脚本人工优先。"""

    async def test_script5_effective_reads_ai_polish(self):
        """人工原文 + AI 润色稿并存 → 脚本5 输入 effective 的 existing_* = AI 润色稿。"""
        fields = _ready_fields(4)
        fields.update(_SCRIPT_AI_OUTPUTS[4])  # AI 润色稿："通风系统" 等
        fields["现有工程控制措施（人工）"] = "人工原文：通风系统（人工补充）"
        fields["脚本4（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        await svc.advance_record(fields)
        assert runner.calls[0][0] == 5
        effective = runner.calls[0][1]
        assert effective["existing_engineering_controls"] == "通风系统"  # AI 值，非人工原文
        assert effective["existing_management_controls"] == "安全操作规程"

    async def test_script8_still_reads_manual_original(self):
        """脚本8 输入仍读 4 个人工原文（_build_script_input(8) 走 _SCRIPT8_MANUAL_MEASURES 不变）。"""
        fields = _ready_fields(8)
        fields["现有工程控制措施（AI）"] = "AI润色稿：通风系统"
        fields["现有工程控制措施（人工）"] = "人工原文：通风系统"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["工程措施排查内容（AI）"] == "（1）检查通风系统。"
        effective = runner.calls[0][1]
        assert effective["engineering_controls"] == "人工原文：通风系统"
        assert effective["management_controls"] == "安全操作规程"

    def test_map_script4_ai_priority(self):
        """map_bitable_to_model：脚本4 四键 AI 优先（AI 非空取 AI，否则回退人工）。"""
        fields = {
            "现有工程控制措施（AI）": "AI润色稿", "现有工程控制措施（人工）": "人工原文",
            "现有管理控制措施（AI）": "", "现有管理控制措施（人工）": "人工原文2",
        }
        model = map_bitable_to_model(fields)
        assert model["existing_engineering_controls"] == "AI润色稿"
        assert model["existing_management_controls"] == "人工原文2"  # AI 空 → 回退人工

    def test_other_scripts_stay_manual_priority(self):
        """其余脚本（如脚本1/3）保持人工优先，不受脚本4 例外影响。"""
        fields = {
            "具体作业活动（AI）": "AI活动", "具体作业活动（人工）": "人工活动",
            "可能性L（固有）（AI）": "3", "可能性L（固有）（人工）": "5",
        }
        model = map_bitable_to_model(fields)
        assert model["specific_activity"] == "人工活动"
        assert model["l_inherent"] == 5.0


class TestScript35Regression:
    """脚本3.5 回归：_ready_fields(3) 不受脚本4 触发反转影响。"""

    async def test_ready_fields_3_still_runs_script3_and_3_5(self):
        outputs = dict(_OUTPUTS)
        outputs[3.5] = SimpleNamespace(risk_label="较大风险")
        runner = _RecordingRunner(outputs)
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(3))
        assert [c[0] for c in runner.calls] == [3, 3.5]
        assert out["可能性L（固有）（AI）"] == 3
        assert out[_FUJIAN_RISK_FIELD] == ["较大风险"]
