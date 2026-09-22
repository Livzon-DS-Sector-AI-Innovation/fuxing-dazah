"""key_risk_op 直读视图对象与镜像口径排序（key_risk_op-direct Ticket 01）。

照 cert_direct/reader.py 模式：

1. KeyRiskOpView：字段名与 KeyRiskOperationReport ORM 完全同名（审计列 created_by/
   updated_by/is_deleted 除外，契约单测固化）；id = 飞书记录 ID（recXXX，本域镜像按
   feishu_record_id 对齐，两路径 id 空间一致）；created_at/updated_at 恒 None
   （Bitable 无自动时间字段——探针核实 52 列无 type 1001/1002）。
2. view_from_record_id：复用镜像同一映射纯函数
   ``KeyRiskOperationReportService.map_bitable_fields``（静态、零 IO，51 字段：
   多作业块 ×{1,2}、三阶段现场确认、申请编号 Url 双列、时长 float、Person/Select
   取 name）；镜像语义在 reader 层复刻：「已删除」排除、report_no 空兜底 BT-xx。
3. sort_like_mirror：API 列表 ORDER BY 契约 start_time DESC NULLS LAST（稳定排序）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.safety.service.key_risk_operation_report import (
    APPLY_STATUS_DELETED,
    KeyRiskOperationReportService,
)

__all__ = [
    "APPLY_STATUS_DELETED",
    "KeyRiskOpView",
    "is_deleted_row",
    "sort_like_mirror",
    "view_from_mapped",
    "view_from_record_id",
]


@dataclass
class KeyRiskOpView:
    """关键风险作业报备行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX；Bitable 无自动时间字段）
    id: str = ""
    feishu_record_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False

    # 来源与主键
    report_no: str = ""
    approval_no_url: str | None = None
    source: str = "bitable"

    # 审批字段
    apply_status: str | None = None
    approval_node: str | None = None
    approval_flow: str | None = None
    current_handler: str | None = None
    initiator_name: str | None = None
    initiator_department: str | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None

    # 作业主信息
    department: str | None = None
    area: str | None = None
    operation_content: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_hours: float | None = None
    notes: str | None = None

    # 安全措施（主作业）
    personal_protection: str | None = None
    preparation_measures: str | None = None
    operation_precautions: str | None = None
    emergency_measures: str | None = None
    guardian: str | None = None
    site_guardian: str | None = None
    dept_safety_officer: str | None = None

    # 多作业块 / 三阶段现场确认
    operations: list[Any] | None = None
    phase_before: dict[str, Any] | None = None
    phase_ongoing: dict[str, Any] | None = None
    phase_after: dict[str, Any] | None = None

    source_id: str | None = None


def view_from_record_id(record_id: str, fields: dict[str, Any]) -> KeyRiskOpView:
    """Bitable 原始 fields dict → 视图对象（映射复用镜像同一纯函数）。

    镜像 sync/handler 的两处调用方语义在此收口：report_no 空 → 兜底
    ``BT-{record_id[-12:]}``；「已删除」行的排除由 reader 层在调用前完成。
    """
    mapped = KeyRiskOperationReportService.map_bitable_fields(fields)
    return view_from_mapped(record_id, mapped)


def view_from_mapped(record_id: str, mapped: dict[str, Any]) -> KeyRiskOpView:
    """映射结果 dict → 视图对象（reader 一次映射复用，避免全量双重映射）。"""
    mapped = dict(mapped)
    mapped["feishu_record_id"] = record_id
    if not mapped.get("report_no"):
        mapped["report_no"] = f"BT-{record_id[-12:]}"
    view = KeyRiskOpView(id=record_id)
    for key, value in mapped.items():
        setattr(view, key, value)
    return view


def is_deleted_mapped(mapped: dict[str, Any]) -> bool:
    """「已删除」申请状态判定（按映射结果，与镜像 sync/_name_of 同口径）。"""
    return mapped.get("apply_status") == APPLY_STATUS_DELETED


def is_deleted_row(fields: dict[str, Any]) -> bool:
    """「已删除」申请状态判定（fields 直判便捷形式）。"""
    return is_deleted_mapped(KeyRiskOperationReportService.map_bitable_fields(fields))


def sort_like_mirror(views: list[KeyRiskOpView]) -> list[KeyRiskOpView]:
    """按镜像 repo.get_key_risk_operation_reports 的 ORDER BY 契约排序（返回新列表）。

    对应 SQL：start_time DESC NULLS LAST。稳定排序：start_time 同值组内保持输入顺序
    （Bitable 无次级时间戳，双路径 tie 组内行序差异属预期，verify 归一比对）。
    """
    rows = list(views)
    rows.sort(key=lambda v: (
        v.start_time is None,
        -(v.start_time.timestamp()) if v.start_time is not None else 0.0,
    ))
    return rows
