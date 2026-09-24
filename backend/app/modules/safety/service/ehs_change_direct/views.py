"""ehs_change 直读视图对象（Ticket 01）。

照 hazard_id_direct/views.py 模式：字段与 EhsChange ORM 同名（工具
query_ehs_changes 13 输出 + keyword 筛选所需 description + 比对所需
标识）。

1. **映射复用**：view_from_record 复用镜像同款纯函数
   ``ehs_change_bitable.map_approval_fields / map_acceptance_fields``
   ——handler `_upsert` 与直读走同一映射，语义天然逐字一致（spec D5）；
2. **形态**：本域两表无公式列（survey_ehs_change 2026-09-24 实测
   type=2 无），mapper 所用 bitable_handler 系提取函数
   （_extract_rich_text/_extract_person_info/_extract_select_values/
   _extract_datetime_ms）对 search 形态（富文本 list<dict> / 多选
   list<str> / 人员 list<dict> / 日期毫秒 int / Url dict）双形态容忍，
   无需 search_to_handler_form 归一化（hazard_id 公式列陷阱不适用）；
3. **跳行规则**：mapper 返 None（申请状态=「已删除」软删信号）→
   视图层返 None，reader 跳过——与 legacy「镜像无此行」语义一致；
4. actual_start/actual_completion 恒 None：状态机端点从未驱动过任何行
   （探针坐实 0/482 非空），直读无损复刻（spec §0.2）；
5. 「变更状态」列在审批表根本不存在（探针坐实）→ bt_change_status
   恒 None 属既有缺陷（工具不输出该字段，spec §0.4 落档不修）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.safety.feishu.ehs_change_bitable import (
    map_acceptance_fields,
    map_approval_fields,
)

__all__ = ["EhsChangeView", "view_from_record"]


@dataclass
class EhsChangeView:
    """EHS 变更行（审批表/验收表合一）的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与排序键（created_time 为 Bitable 系统字段，reader 侧注入；
    # 排序键受控偏差见 spec D3：legacy created_at desc → created_time desc）
    record_id: str = ""
    kind: str = ""  # approval / acceptance（feishu_table_id 同名）
    created_time_ms: int | None = None

    # 业务字段（与 ORM 同名；工具 13 输出 + description（keyword 筛选））
    change_no: str | None = None
    title: str = ""
    change_type: str | None = None
    change_grade: str = "general"
    department: str | None = None
    location_unit: str | None = None
    status: str = "draft"
    description: str | None = None
    expected_start: datetime | None = None
    expected_completion: datetime | None = None
    actual_start: datetime | None = None
    actual_completion: datetime | None = None
    applicant_name: str | None = None
    ai_review_status: str = "none"


def view_from_record(
    kind: str,
    record_id: str,
    fields: dict[str, Any],
    *,
    created_time_ms: int | None = None,
) -> EhsChangeView | None:
    """Bitable 行（search 形态）→ 视图对象；申请状态「已删除」返 None（跳行）。"""
    mapper = map_approval_fields if kind == "approval" else map_acceptance_fields
    mapped = mapper(fields)
    if mapped is None:
        return None
    return EhsChangeView(
        record_id=record_id,
        kind=kind,
        created_time_ms=created_time_ms,
        change_no=mapped.get("change_no"),
        title=mapped.get("title") or "",
        change_type=mapped.get("change_type"),
        change_grade=mapped.get("change_grade") or "general",
        department=mapped.get("department"),
        location_unit=mapped.get("location_unit"),
        status=mapped.get("status") or "draft",
        description=mapped.get("description"),
        expected_start=mapped.get("expected_start"),
        expected_completion=mapped.get("expected_completion"),
        actual_start=mapped.get("actual_start"),
        actual_completion=mapped.get("actual_completion"),
        applicant_name=mapped.get("applicant_name"),
        ai_review_status=mapped.get("ai_review_status") or "none",
    )
