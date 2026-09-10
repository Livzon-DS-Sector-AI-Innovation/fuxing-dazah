"""Ticket 04 — HazardIdentificationBitableService 纯逻辑编排核心测试。

覆盖：decide_next_script 状态机全节点分支、advance_record 各脚本触发/幂等/前置不足/
卡死自愈对账/严格顺序门控/附录B异常，map_ai_output_to_bitable 回写格式
（硬边界：只写（AI）字段，不写节点；节点由 advance_record 审核驱动对账负责）。
使用 MockAIService 模式注入 fake run_script + fake attachment_parser，无 DB/无网络。
"""

from types import SimpleNamespace

from app.modules.safety.service.hazard_identification_bitable import (
    HazardIdentificationBitableService,
)

# ── 状态机节点标签（与 spec.md §4 / 设计文档一致）──
NODES = {
    1: "待危险源信息AI提取",
    2: "待AI危险源辨识",
    3: "待AI固有风险评价",
    4: "待AI输入现有控制措施",
    5: "待AI评价残余风险",
    6: "待AI提出建议措施",
    7: "待AI评价采取措施后的残余风险",
    8: "待人工审核检查清单",
}

_ATTACHMENT = "https://xxx.feishu.cn/wiki/Wxyz123"

# 各脚本 AI 输出字段（真实 Bitable 字段名）→ 样本值。
# `_ready_fields` 用它构造"前置脚本 1..N-1 全部有输出"的就绪态（全链门控需要）。
_SCRIPT_AI_OUTPUTS: dict[int, dict[str, str]] = {
    1: {"具体作业活动（AI）": "人工投料", "设备设施（AI）": "发酵罐", "原辅料（AI）": "培养基"},
    2: {
        "危险类型（AI）": "设备设施缺陷", "可能导致事故（AI）": "烫伤",
        "不规范作业行为表现（AI）": "未佩戴防护",
    },
    3: {"可能性L（固有）（AI）": "3", "暴露频率E（固有）（AI）": "6", "严重性C（固有）（AI）": "15"},
    4: {
        "现有工程控制措施（AI）": "通风系统", "现有管理控制措施（AI）": "安全操作规程",
        "现有个人防护措施（AI）": "防护面屏", "现有应急措施（AI）": "应急物资",
    },
    5: {"可能性L(残余）（AI）": "1", "暴露频率E(残余）（AI）": "3", "严重程度C（残余）（AI）": "7"},
    6: {
        "是否需提出建议措施（AI）": "是", "建议措施类型（AI）": "工程技术",
        "建议措施内容（AI）": "增设联锁", "建议措施优先级（AI）": "高",
    },
    7: {"L（建议措施采取后）（AI）": "0.5", "E（建议措施采取后）（AI）": "2", "C（建议措施采取后）（AI）": "7"},
    8: {
        "工程措施排查内容（AI）": "（1）检查通风系统。", "管理措施排查内容（AI）": "（1）检查操作规程。",
        "个人防护措施排查内容（AI）": "（1）检查面屏。", "应急措施排查内容（AI）": "（1）检查应急物资。",
    },
}


def _ready_fields(script: int) -> dict:
    """构造一个到达脚本 N 触发就绪态的 Bitable 字段 dict。

    节点=N 对应标签；前置脚本 1..N-1 全部「已审核」**且输出已存在**（全链完整）；
    必要输入非空；本脚本 AI 输出为空。
    """
    fields: dict = {"AI流程节点进度": NODES[script]}
    for i in range(1, script):
        fields.update(_SCRIPT_AI_OUTPUTS[i])
        fields[f"脚本{i}（人工审核状态）"] = "已审核"

    if script == 1:
        fields["岗位（人工）"] = "发酵车间主操"
        fields["生产步骤（人工）"] = "发酵罐灭菌操作"
        fields["岗位资料附件（人工）"] = _ATTACHMENT
    elif script == 4:
        # 优化2：脚本4 触发反转——需要 4 类现有控制措施（人工）非空
        fields.update({
            "现有工程控制措施（人工）": "通风系统", "现有管理控制措施（人工）": "安全操作规程",
            "现有个人防护措施（人工）": "防护面屏", "现有应急措施（人工）": "应急物资",
        })
    elif script == 8:
        # 脚本8 专取 4 类现有控制措施（人工）作为输入
        fields.update({
            "现有工程控制措施（人工）": "通风系统", "现有管理控制措施（人工）": "安全操作规程",
            "现有个人防护措施（人工）": "防护面屏", "现有应急措施（人工）": "应急物资",
        })
    return fields


# ── fake 协作对象 ──
def _out(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _lec_output(l_val, e_val, c_val, d=None, level=None, label=None) -> SimpleNamespace:
    """LEC 脚本输出：含公式字段（D/等级），用于验证它们不被回写。"""
    return SimpleNamespace(lec=SimpleNamespace(
        l_value=l_val, e_value=e_val, c_value=c_val, d_value=d, risk_level=level, risk_label=label,
    ))


_OUTPUTS = {
    1: _out(specific_activity="人工投料", equipment_facilities="发酵罐、蒸汽管道", raw_auxiliary_materials="培养基、蒸汽"),
    2: _out(hazard_type="设备设施缺陷", possible_accident="烫伤、灼伤", unsafe_behavior="未佩戴防护"),
    3: _lec_output(3, 6, 15, d=270, level="level_1", label="重大风险"),
    4: _out(engineering_controls="通风系统", management_controls="安全操作规程", ppe="防护面屏", emergency_measures="应急物资"),
    5: _lec_output(1, 3, 7, d=21, level="level_3", label="一般风险"),
    6: _out(needs_recommendation="是", recommendation_type="工程技术", recommendation_content="增设联锁", recommendation_priority="高"),
    7: _lec_output(0.5, 2, 7, d=7, level="level_4", label="低风险"),
    8: _out(engineering_items="（1）检查通风系统。", management_items="（1）检查操作规程。", ppe_items="（1）检查面屏。", emergency_items="（1）检查应急物资。"),
}


class _RecordingRunner:
    """记录调用并返回预设输出的 fake run_script。"""

    def __init__(self, outputs: dict | None = None):
        self.outputs = outputs or _OUTPUTS
        self.calls: list[tuple[int, dict]] = []

    async def __call__(self, script: int, effective: dict):
        self.calls.append((script, dict(effective)))
        return self.outputs.get(script)


def _boundary_ok(result: dict) -> bool:
    """回写硬边界：只允许「（AI）」输出字段 + AI流程节点进度。"""
    for key in result:
        if key == "AI流程节点进度":
            continue
        if not key.endswith("（AI）"):
            return False
        if "（人工）" in key:
            return False
        if key.startswith(("风险值", "风险等级", "管控等级", "记录")):
            return False
    return True


def _async_parser(text: str | None):
    """返回固定文本的 fake 附件解析器（async 接缝）。"""
    async def _parser(source: str) -> str | None:
        return text
    return _parser


def _raising_parser(exc: Exception):
    """抛异常的 fake 附件解析器（async 接缝）。"""
    async def _parser(source: str) -> str | None:
        raise exc
    return _parser


class TestDecideNextScript:
    """状态机判定：节点匹配 + 前置审核 + 必要输入 + 幂等。"""

    async def test_all_scripts_ready(self):
        svc = HazardIdentificationBitableService()
        for script in range(1, 9):
            fields = _ready_fields(script)
            assert svc.decide_next_script(fields) == script, f"脚本{script} 应可触发"

    def test_node_mismatch_returns_none(self):
        fields = _ready_fields(2)
        fields["AI流程节点进度"] = "待AI固有风险评价"  # 脚本3的节点，但必要输入是脚本2输出
        svc = HazardIdentificationBitableService()
        # 脚本3 的必要输入为空 → None
        assert svc.decide_next_script(fields) is None

    def test_unknown_or_empty_node_returns_none(self):
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script({}) is None
        assert svc.decide_next_script({"AI流程节点进度": "AI 流程结束"}) is None
        assert svc.decide_next_script({"AI流程节点进度": "未知节点"}) is None

    def test_prev_not_approved_returns_none(self):
        fields = _ready_fields(3)
        fields["脚本2（人工审核状态）"] = "待审核"
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) is None

    def test_prev_rejected_returns_none(self):
        fields = _ready_fields(4)
        fields["脚本3（人工审核状态）"] = "已驳回"
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) is None

    def test_script1_has_no_prev_gate(self):
        # 脚本1 无前置审核，只要节点+输入满足即可
        fields = _ready_fields(1)
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) == 1

    def test_required_input_empty_blocks(self):
        svc = HazardIdentificationBitableService()
        # 脚本4：任一人工措施（现有工程控制措施（人工）等）为空 → 阻塞（优化2 触发反转）
        fields = _ready_fields(4)
        fields["现有工程控制措施（人工）"] = ""
        assert svc.decide_next_script(fields) is None
        # 脚本8：任一人工措施为空 → 阻塞
        fields8 = _ready_fields(8)
        fields8["现有工程控制措施（人工）"] = ""
        assert svc.decide_next_script(fields8) is None
        # 脚本1：附件为空 → 阻塞
        fields1 = _ready_fields(1)
        fields1["岗位资料附件（人工）"] = ""
        assert svc.decide_next_script(fields1) is None

    def test_idempotency_ai_output_present_blocks(self):
        svc = HazardIdentificationBitableService()
        fields = _ready_fields(2)
        # 脚本2 AI 输出已存在 → 幂等跳过
        fields["危险类型（AI）"] = "设备设施缺陷"
        assert svc.decide_next_script(fields) is None

    def test_manual_input_counts_toward_required(self):
        # 人工字段可替代 AI 字段作为必要输入（人工优先）；AI 输出全空以满足幂等
        fields = _ready_fields(2)
        for key in ("具体作业活动（AI）", "设备设施（AI）", "原辅料（AI）"):
            fields.pop(key, None)
        fields["具体作业活动（人工）"] = "人工投料（手工确认）"
        fields["设备设施（人工）"] = "发酵罐"
        fields["原辅料（人工）"] = "培养基"
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) == 2


class TestMapAiOutputToBitable:
    """AI 输出 → Bitable 回写格式（硬边界 + 不写节点）。"""

    def test_non_lec_scripts_map_ai_fields(self):
        svc = HazardIdentificationBitableService()
        out = svc.map_ai_output_to_bitable(2, _OUTPUTS[2])
        # 危险类型（AI）为 Bitable 多选字段 → 回写必须为 list[选项名]
        assert out["危险类型（AI）"] == ["设备设施缺陷"]
        assert out["可能导致事故（AI）"] == "烫伤、灼伤"
        assert "AI流程节点进度" not in out

    def test_multiselect_fields_written_as_list(self):
        """危险类型（AI）/建议措施类型（AI）为 Bitable 多选字段 → 回写必须为 list[选项名]。"""
        svc = HazardIdentificationBitableService()
        out2 = svc.map_ai_output_to_bitable(2, _OUTPUTS[2])
        out6 = svc.map_ai_output_to_bitable(6, _OUTPUTS[6])
        assert out2["危险类型（AI）"] == ["设备设施缺陷"]
        assert out6["建议措施类型（AI）"] == ["工程技术"]

    def test_multiselect_joined_string_split(self):
        """多选字段「、」连接字符串 → 回写按「、」拆分为 list[选项名]。"""
        svc = HazardIdentificationBitableService()
        out2 = svc.map_ai_output_to_bitable(
            2, _out(
                hazard_type="化学灼伤、腐蚀灼伤",
                possible_accident="盐酸喷溅造成灼伤",
                unsafe_behavior="未确认罐压即开盖",
            )
        )
        out6 = svc.map_ai_output_to_bitable(
            6, _out(
                needs_recommendation="是", recommendation_type="工程技术、培训教育",
                recommendation_content="增设联锁；开展开盖作业专项培训",
                recommendation_priority="高",
            )
        )
        assert out2["危险类型（AI）"] == ["化学灼伤", "腐蚀灼伤"]
        assert out6["建议措施类型（AI）"] == ["工程技术", "培训教育"]

    def test_script1_maps_three_outputs(self):
        svc = HazardIdentificationBitableService()
        out = svc.map_ai_output_to_bitable(1, _OUTPUTS[1])
        assert out["具体作业活动（AI）"] == "人工投料"
        assert out["设备设施（AI）"] == "发酵罐、蒸汽管道"
        assert out["原辅料（AI）"] == "培养基、蒸汽"
        assert "AI流程节点进度" not in out

    def test_script8_maps_four_check_items(self):
        svc = HazardIdentificationBitableService()
        out = svc.map_ai_output_to_bitable(8, _OUTPUTS[8])
        assert out["工程措施排查内容（AI）"] == "（1）检查通风系统。"
        assert out["应急措施排查内容（AI）"] == "（1）检查应急物资。"
        assert "AI流程节点进度" not in out

    def test_lec_scripts_only_l_e_c_formula_excluded(self):
        svc = HazardIdentificationBitableService()
        for script, l_field, e_field, c_field in [
            (3, "可能性L（固有）（AI）", "暴露频率E（固有）（AI）", "严重性C（固有）（AI）"),
            (5, "可能性L(残余）（AI）", "暴露频率E(残余）（AI）", "严重程度C（残余）（AI）"),
            (7, "L（建议措施采取后）（AI）", "E（建议措施采取后）（AI）", "C（建议措施采取后）（AI）"),
        ]:
            out = svc.map_ai_output_to_bitable(script, _lec_output(1, 2, 3, d=999, level="level_1", label="重大风险"))
            assert out[l_field] == 1
            assert out[e_field] == 2
            assert out[c_field] == 3
            # 公式字段绝不回写
            assert "风险值 D" not in out and "风险等级" not in out
            assert "AI流程节点进度" not in out

    def test_all_scripts_respect_write_boundary(self):
        svc = HazardIdentificationBitableService()
        for script in range(1, 9):
            out = svc.map_ai_output_to_bitable(script, _OUTPUTS[script])
            assert _boundary_ok(out), f"脚本{script} 回写越界: {out}"

    def test_no_node_progress_written(self):
        """RUN 不推进节点：map_ai_output_to_bitable 只回写（AI）字段（审核驱动）。"""
        svc = HazardIdentificationBitableService()
        for script in range(1, 9):
            out = svc.map_ai_output_to_bitable(script, _OUTPUTS[script])
            assert out, f"脚本{script} 应有 AI 输出回写"
            assert "AI流程节点进度" not in out, f"脚本{script} 不应写节点"


class TestAdvanceRecord:
    """advance_record 全链路：判定 → 构建输入 → 注入执行 → 回写映射。"""

    async def test_advance_script2(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        fields = _ready_fields(2)
        out = await svc.advance_record(fields)
        # 危险类型（AI）为 Bitable 多选字段 → 回写必须为 list[选项名]
        assert out["危险类型（AI）"] == ["设备设施缺陷"]
        # RUN 不推进节点：节点待脚本2审核通过后由对账推进
        assert "AI流程节点进度" not in out
        assert runner.calls[0][0] == 2

    async def test_advance_script8_passes_manual_measures(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(_ready_fields(8))
        assert out["工程措施排查内容（AI）"] == "（1）检查通风系统。"
        assert "AI流程节点进度" not in out
        effective = runner.calls[0][1]
        assert effective["engineering_controls"] == "通风系统"
        assert effective["emergency_measures"] == "应急物资"

    async def test_advance_script1_parses_attachment(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(
            run_script=runner,
            attachment_parser=_async_parser("附件解析后的文本"),
        )
        out = await svc.advance_record(_ready_fields(1))
        assert out["具体作业活动（AI）"] == "人工投料"
        assert runner.calls[0][0] == 1
        assert runner.calls[0][1]["attachment_text"] == "附件解析后的文本"
        assert runner.calls[0][1]["position"] == "发酵车间主操"

    async def test_script1_attachment_parse_failure_waits(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(
            run_script=runner,
            attachment_parser=_async_parser(None),
        )
        out = await svc.advance_record(_ready_fields(1))
        assert out is None
        assert runner.calls == []

    async def test_script1_attachment_parser_raises_waits(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(
            run_script=runner,
            attachment_parser=_raising_parser(RuntimeError("下载失败")),
        )
        out = await svc.advance_record(_ready_fields(1))
        assert out is None
        assert runner.calls == []

    async def test_not_triggerable_returns_none(self):
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        fields = _ready_fields(2)
        fields["脚本1（人工审核状态）"] = "待审核"
        assert await svc.advance_record(fields) is None
        assert runner.calls == []

    async def test_runner_returns_none_returns_none(self):
        async def empty_runner(script, effective):
            return None
        svc = HazardIdentificationBitableService(run_script=empty_runner)
        assert await svc.advance_record(_ready_fields(3)) is None

    async def test_no_runner_injected_returns_none(self):
        svc = HazardIdentificationBitableService()
        assert await svc.advance_record(_ready_fields(2)) is None

    async def test_each_script_runs_and_returns_ai_fields(self):
        """8 个脚本 RUN 均返回 AI 回写，且节点不进回写（审核驱动）。"""
        for script in range(1, 9):
            runner = _RecordingRunner()
            svc = HazardIdentificationBitableService(
                run_script=runner,
                attachment_parser=_async_parser("解析文本"),  # 脚本1 需要附件解析器
            )
            out = await svc.advance_record(_ready_fields(script))
            assert out is not None, f"脚本{script} 应推进"
            assert runner.calls[0][0] == script, f"脚本{script} 应运行"
            assert "AI流程节点进度" not in out, f"脚本{script} 运行不应推进节点（审核驱动）"


class TestMapAttachmentForScript1:
    """附件 URL/文件 token → 文本（注入解析器，无 IO）。"""

    async def test_plain_string_url(self):
        svc = HazardIdentificationBitableService(attachment_parser=_async_parser("文本"))
        assert await svc.map_attachment_for_script1({"岗位资料附件（人工）": _ATTACHMENT}) == "文本"

    async def test_rich_text_attachment(self):
        svc = HazardIdentificationBitableService(attachment_parser=_async_parser("文本"))
        fields = {"岗位资料附件（人工）": [{"type": "text", "text": _ATTACHMENT}]}
        assert await svc.map_attachment_for_script1(fields) == "文本"

    async def test_empty_attachment_returns_none(self):
        svc = HazardIdentificationBitableService(attachment_parser=_async_parser("文本"))
        assert await svc.map_attachment_for_script1({}) is None
        assert await svc.map_attachment_for_script1({"岗位资料附件（人工）": ""}) is None

    async def test_no_parser_returns_none(self):
        svc = HazardIdentificationBitableService()
        assert await svc.map_attachment_for_script1({"岗位资料附件（人工）": _ATTACHMENT}) is None

    async def test_parser_raising_returns_none(self):
        svc = HazardIdentificationBitableService(attachment_parser=_raising_parser(RuntimeError("boom")))
        assert await svc.map_attachment_for_script1({"岗位资料附件（人工）": _ATTACHMENT}) is None


class TestReconcileSelfHealing:
    """审核驱动自愈对账：当前节点脚本完整（输出+已审核）→ 推进节点；可续跑则续跑。"""

    async def test_script8_complete_advances_to_completed(self):
        """节点=脚本8，输出+已审核 → 推进「AI 流程结束」，不再执行任何脚本。"""
        fields = _ready_fields(8)
        fields.update(_SCRIPT_AI_OUTPUTS[8])
        fields["脚本8（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out == {"AI流程节点进度": "AI 流程结束"}
        assert runner.calls == []

    async def test_script5_complete_advances_and_runs_script6(self):
        """节点=脚本5，输出+已审核 → 推进到脚本6节点并续跑脚本6。"""
        fields = _ready_fields(5)
        fields.update(_SCRIPT_AI_OUTPUTS[5])
        fields["脚本5（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[6]
        assert runner.calls[0][0] == 6
        assert out["是否需提出建议措施（AI）"] == "是"

    async def test_script3_complete_advances_and_runs_script4_when_manual_filled(self):
        """节点=脚本3，输出+已审核 + 4 类人工措施已填 → 推进到脚本4节点并续跑脚本4（AI 润色）。"""
        fields = _ready_fields(3)
        fields.update(_SCRIPT_AI_OUTPUTS[3])
        fields["脚本3（人工审核状态）"] = "已审核"
        fields.update({
            "现有工程控制措施（人工）": "通风系统", "现有管理控制措施（人工）": "安全操作规程",
            "现有个人防护措施（人工）": "防护面屏", "现有应急措施（人工）": "应急物资",
        })
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[4]
        assert runner.calls[0][0] == 4
        assert out["现有工程控制措施（AI）"] == "通风系统"

    async def test_script3_complete_advances_node_only_when_manual_empty(self):
        """节点=脚本3，输出+已审核但 4 类人工措施未填 → 仅推进节点，不运行脚本4（等人工填写）。"""
        fields = _ready_fields(3)
        fields.update(_SCRIPT_AI_OUTPUTS[3])
        fields["脚本3（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out == {"AI流程节点进度": NODES[4]}
        assert runner.calls == []

    async def test_script2_complete_advances_node_only_when_input_missing(self):
        """节点=脚本2，输出+已审核，但脚本3必要输入缺失 → 只推进节点不运行。"""
        fields = _ready_fields(2)
        fields.update(_SCRIPT_AI_OUTPUTS[2])
        fields["脚本2（人工审核状态）"] = "已审核"
        fields.pop("不规范作业行为表现（AI）", None)  # 脚本3 的输入，缺失 → 不运行
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out == {"AI流程节点进度": NODES[3]}
        assert runner.calls == []

    async def test_script2_output_present_not_approved_waits(self):
        """节点=脚本2，输出存在但未审核 → 等审（不推进、不运行）。"""
        fields = _ready_fields(2)
        fields.update(_SCRIPT_AI_OUTPUTS[2])   # 脚本2 输出存在但未「已审核」
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None
        assert runner.calls == []


class TestStrictOrderGates:
    """全链顺序门控：任一前置脚本未完整（无输出/未审核）→ 整条链阻塞。"""

    async def test_previous_approved_but_no_output_blocks(self):
        """脚本1 已审核但输出缺失 → 脚本2 前置链断裂，不推进不运行。"""
        fields = _ready_fields(2)
        for key in ("具体作业活动（AI）", "设备设施（AI）", "原辅料（AI）"):
            fields.pop(key, None)   # 脚本1 输出全缺
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None
        assert runner.calls == []

    async def test_mid_chain_not_approved_blocks(self):
        """脚本3 未审核（中段前置断裂）→ 脚本6 不推进不运行。"""
        fields = _ready_fields(6)
        fields["脚本3（人工审核状态）"] = "待审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None
        assert runner.calls == []

    async def test_previous_rejected_blocks(self):
        """脚本1 已驳回 → 脚本2 前置链断裂。"""
        fields = _ready_fields(2)
        fields["脚本1（人工审核状态）"] = "已驳回"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None
        assert runner.calls == []


class TestCompletedAnomaly:
    """附录 B：节点=「AI 流程结束」但脚本8未完整 → 不执行、记异常、等人工修复。"""

    async def test_completed_node_with_incomplete_script8_returns_none(self):
        fields = _ready_fields(8)
        fields["AI流程节点进度"] = "AI 流程结束"   # 无脚本8输出 → 名不副实
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None
        assert runner.calls == []

    async def test_completed_node_with_complete_script8_no_run(self):
        fields = _ready_fields(8)
        fields.update(_SCRIPT_AI_OUTPUTS[8])
        fields["脚本8（人工审核状态）"] = "已审核"
        fields["AI流程节点进度"] = "AI 流程结束"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        assert await svc.advance_record(fields) is None   # 已完成，无脚本可执行
        assert runner.calls == []


class TestScript7Skip:
    """脚本7（建议措施后风险评价）在「无需建议措施」时跳过：不执行、节点直接越过。"""

    async def test_script7_not_runnable_when_no_recommendation(self):
        """need=否 → 脚本7 节点不触发执行。"""
        fields = _ready_fields(7)
        fields["是否需提出建议措施（AI）"] = "否"
        fields["建议措施内容（AI）"] = ""   # 无建议内容 → 输入也缺，双保险
        svc = HazardIdentificationBitableService()
        assert svc.decide_next_script(fields) is None

    async def test_node_at_script7_need_no_advances_past(self):
        """节点=脚本7 + need=否 → 越过脚本7 直接到脚本8（无需建议即视为完成）。"""
        fields = _ready_fields(7)
        fields["是否需提出建议措施（AI）"] = "否"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[8]
        assert runner.calls == []   # 脚本7 跳过不运行

    async def test_script6_approved_need_no_advances_past_script7(self):
        """脚本6 已审核 + need=否 → 节点越过脚本7 到脚本8（无需建议路径，防新记录死锁）。"""
        fields = _ready_fields(6)
        fields.update(_SCRIPT_AI_OUTPUTS[6])
        fields["是否需提出建议措施（AI）"] = "否"
        fields["脚本6（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out["AI流程节点进度"] == NODES[8]
        assert runner.calls == []   # 脚本6 已审核不重跑；脚本7 跳过不运行

    async def test_script8_complete_need_no_advances_to_completed(self):
        """need=否 + 脚本8 完整 → 越过脚本7 直达「AI 流程结束」。"""
        fields = _ready_fields(8)
        fields.update(_SCRIPT_AI_OUTPUTS[6])
        fields["是否需提出建议措施（AI）"] = "否"
        fields["脚本6（人工审核状态）"] = "已审核"
        fields.update(_SCRIPT_AI_OUTPUTS[8])
        fields["脚本8（人工审核状态）"] = "已审核"
        runner = _RecordingRunner()
        svc = HazardIdentificationBitableService(run_script=runner)
        out = await svc.advance_record(fields)
        assert out == {"AI流程节点进度": "AI 流程结束"}
        assert runner.calls == []
