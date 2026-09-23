"""hazard_id 直读视图对象（Ticket 02）。

照 oh_direct/views.py 模式：字段与 HazardIdentification ORM 同名（工具
query_hazard_identifications 15 输出中 Bitable 可推导的 14 个）。

1. **映射复用**：view_from_record 复用镜像同款纯函数
   ``hazard_identification_bitable.map_bitable_to_model``——handler
   `_upsert_mirror` 与直读走同一映射，语义天然逐字一致（spec D3）；
2. **search 形态归一化**（spec D3，探针坐实的唯一形态差）：公式列
   （type=20，如 风险值D（固有）（人工）6 列）search 返回
   ``{"type": 2, "value": [270]}`` 而 get_record 返回裸数值 270——先经
   ``search_to_handler_form`` 归一化再进映射；其余形态（富文本 list<dict> /
   多选 list<str> / 人员 list<dict> / 附件 dict{link} / 数值 int）映射函数
   的 _text/_person_name/_attachment_source 本就双形态容忍，原样透传；
3. hazard_id_no 派生同 handler：``HI-{record_id[-12:]}``（探针 595 活行零冲突）；
4. overall_status 由 map 内节点推导（「AI 流程结束」→completed 否则 draft）；
5. department 不在视图上——identity 按提交人现算，由查询层经 departments
   映射注入过滤与输出（保 TTL 缓存视图只读约定，spec D7）；
6. feishu_url 恒 None 属输出层常量（镜像自始无写入方，探针 0/595，quirk 落档）；
7. 跳行规则：无（镜像种群=全部行，无空行跳过语义，spec D7）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.safety.service.hazard_identification_bitable import (
    map_bitable_to_model,
)

__all__ = [
    "HazardIdentificationView",
    "search_to_handler_form",
    "view_from_record",
]


def search_to_handler_form(fields: dict[str, Any]) -> dict[str, Any]:
    """search 响应字段 → handler（get_record）形态（纯函数，浅适配）。

    仅归一化公式列包裹形态：值形如 dict 且含 ``type`` 与单元素 list ``value``
    时取 ``value[0]``；多元素 value 不动（映射目标 D 列恒单元素，保守不猜）。
    其余形态原样透传。
    """
    adapted: dict[str, Any] = {}
    for name, value in fields.items():
        if (
            isinstance(value, dict)
            and "type" in value
            and isinstance(value.get("value"), list)
            and len(value["value"]) == 1
        ):
            adapted[name] = value["value"][0]
        else:
            adapted[name] = value
    return adapted


@dataclass
class HazardIdentificationView:
    """危险源辨识表行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与排序键（created_time 为 Bitable 系统字段，reader 侧注入；
    # 排序键受控偏差见 spec D5）
    record_id: str = ""
    created_time_ms: int | None = None

    # 业务字段（与 ORM 同名；工具 15 输出的 Bitable 可推导子集）
    hazard_id_no: str = ""
    position: str | None = None
    production_step: str | None = None
    specific_activity: str | None = None
    hazard_type: str | None = None
    possible_accident: str | None = None
    inherent_risk_label: str | None = None
    residual_risk_label: str | None = None
    post_risk_label: str | None = None
    control_level: str | None = None
    recommendation_content: str | None = None
    overall_status: str = "draft"
    submitter_name: str | None = None


def view_from_record(
    record_id: str,
    fields: dict[str, Any],
    *,
    created_time_ms: int | None = None,
) -> HazardIdentificationView:
    """Bitable 行（search 形态）→ 视图对象（纯函数，无跳行规则）。"""
    model = map_bitable_to_model(
        search_to_handler_form(fields),
        feishu_record_id=record_id,
    )
    return HazardIdentificationView(
        record_id=record_id,
        created_time_ms=created_time_ms,
        hazard_id_no=f"HI-{record_id[-12:]}",
        position=model.get("position"),
        production_step=model.get("production_step"),
        specific_activity=model.get("specific_activity"),
        hazard_type=model.get("hazard_type"),
        possible_accident=model.get("possible_accident"),
        inherent_risk_label=model.get("inherent_risk_label"),
        residual_risk_label=model.get("residual_risk_label"),
        post_risk_label=model.get("post_risk_label"),
        control_level=model.get("control_level"),
        recommendation_content=model.get("recommendation_content"),
        overall_status=model.get("overall_status") or "draft",
        submitter_name=model.get("submitter_name"),
    )
