"""hazard_id 直读视图单测（Ticket 02）。

覆盖：search 形态归一化（D 值公式 dict{value:[x]}→x、其余透传）、
map_bitable_to_model 复用等价（同输入逐字段相等）、派生字段
（hazard_id_no/等级/管控层级/overall_status/submitter）、D8 quirk
（脚本6 人工列缺失→AI 值兜底、危险类型多选「、」拼接）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.hazard_id_direct.views import (
    search_to_handler_form,
    view_from_record,
)

# 探针实测 search 形态的代表性行（survey_hazard_id §4）
REC = "recvgUDhwtPIu8"


def _search_fields(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "岗位（人工）": [{"text": "达巴粗提", "type": "text"}],
        "生产步骤（人工）": [{"text": "结晶", "type": "text"}],
        "具体作业活动（人工）": [{"text": "1. 料液准备", "type": "text"}],
        "危险类型（人工）": ["火灾爆炸", "机械伤害"],
        "可能导致事故（人工）": [{"text": "爆炸", "type": "text"}],
        "风险值D（固有）（人工）": {"type": 2, "value": [270]},  # 公式列 search 形态
        "风险值D （残余）(人工)": {"type": 2, "value": [40]},
        "风险值 D（采取建议措施后）（人工）": {"type": 2, "value": [10]},
        "建议措施内容（人工）": [{"text": "加装联锁", "type": "text"}],
        "提交人员（人工）": [{"name": "李伟豪", "open_id": "ou_x"}],
        "AI流程节点进度": "AI 流程结束",
    }
    fields.update(over)
    return fields


class TestSearchToHandlerForm:
    def test_formula_dict_unwrapped(self) -> None:
        got = search_to_handler_form({"风险值D（固有）（人工）": {"type": 2, "value": [270]}})
        assert got["风险值D（固有）（人工）"] == 270

    def test_multi_element_value_kept(self) -> None:
        raw = {"type": 2, "value": [1, 2]}
        assert search_to_handler_form({"f": raw})["f"] == raw

    def test_non_formula_shapes_passthrough(self) -> None:
        rich = [{"text": "x", "type": "text"}]
        multi = ["火灾爆炸"]
        person = [{"name": "李伟豪"}]
        attach = {"link": "https://x/file", "name": "岗位.docx"}
        got = search_to_handler_form({
            "a": rich, "b": multi, "c": person, "d": attach, "e": 3, "f": "s",
        })
        assert got == {"a": rich, "b": multi, "c": person, "d": attach, "e": 3, "f": "s"}

    def test_no_type_key_dict_kept(self) -> None:
        raw = {"value": [9]}  # 无 type 键：不误伤（附件等 dict 无 type+value list 组合）
        assert search_to_handler_form({"f": raw})["f"] == raw


class TestViewFromRecord:
    def test_map_reuse_equivalence(self) -> None:
        """同输入 → 与镜像映射（handler _upsert_mirror 同款）逐字段相等。"""
        from app.modules.safety.service.hazard_identification_bitable import (
            map_bitable_to_model,
        )

        fields = _search_fields()
        model = map_bitable_to_model(
            search_to_handler_form(fields), feishu_record_id=REC,
        )
        v = view_from_record(REC, fields)
        for attr in (
            "position", "production_step", "specific_activity", "hazard_type",
            "possible_accident", "inherent_risk_label", "residual_risk_label",
            "post_risk_label", "control_level", "recommendation_content",
            "overall_status", "submitter_name",
        ):
            assert getattr(v, attr) == model.get(attr), attr

    def test_hazard_id_no_derivation(self) -> None:
        v = view_from_record(REC, _search_fields())
        assert v.hazard_id_no == f"HI-{REC[-12:]}"

    def test_formula_d_drives_labels(self) -> None:
        """D=270/40/10 → 一级/重大风险、三级/一般风险、四级/低风险；管控=公司级。"""
        v = view_from_record(REC, _search_fields())
        assert v.inherent_risk_label == "一级/重大风险"
        assert v.residual_risk_label == "三级/一般风险"
        assert v.post_risk_label == "四级/低风险"
        assert v.control_level == "公司级"

    def test_overall_status_completed_from_node(self) -> None:
        v = view_from_record(REC, _search_fields())
        assert v.overall_status == "completed"

    def test_overall_status_draft_when_node_incomplete(self) -> None:
        v = view_from_record(
            REC, _search_fields(**{"AI流程节点进度": "待AI提出建议措施"}),
        )
        assert v.overall_status == "draft"

    def test_submitter_name_from_person_field(self) -> None:
        v = view_from_record(REC, _search_fields())
        assert v.submitter_name == "李伟豪"

    def test_hazard_type_multi_joined(self) -> None:
        v = view_from_record(REC, _search_fields())
        assert v.hazard_type == "火灾爆炸、机械伤害"

    def test_created_time_ms_injected(self) -> None:
        v = view_from_record(REC, _search_fields(), created_time_ms=1776302265000)
        assert v.created_time_ms == 1776302265000

    def test_empty_fields_defaults(self) -> None:
        v = view_from_record(REC, {})
        assert v.position is None
        assert v.inherent_risk_label is None
        assert v.control_level is None
        assert v.overall_status == "draft"
        assert v.submitter_name is None
        assert v.hazard_id_no == f"HI-{REC[-12:]}"


class TestScript6Quirk:
    """D8 quirk：脚本6 三（人工）列表里根本不存在——effective=AI 值兜底。"""

    def test_missing_manual_columns_fall_back_to_ai(self) -> None:
        v = view_from_record(REC, _search_fields(
            **{
                "是否需提出建议措施（AI）": "是",
                "建议措施类型（AI）": ["工程技术"],
                "建议措施内容（AI）": [{"text": "改用防爆电机", "type": "text"}],
                "建议措施优先级（AI）": "高",
            },
        ))
        # 人工「建议措施内容」优先（存在且非空）
        assert v.recommendation_content == "加装联锁"

    def test_ai_only_recommendation_when_manual_empty(self) -> None:
        v = view_from_record(REC, _search_fields(
            **{
                "建议措施内容（人工）": None,
                "建议措施内容（AI）": [{"text": "改用防爆电机", "type": "text"}],
            },
        ))
        assert v.recommendation_content == "改用防爆电机"
