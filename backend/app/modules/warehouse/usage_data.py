"""原辅料领料（material_outbound）读取层（V3.0 分期D Ticket 06，§4.4⑤）。

车间周用量简化版数据源：按领用部门聚合近 7 天领料（「按车间用量计划」
对比维度设计列为远期）。material_outbound 已注册（分期C），读取走
WarehouseBitableAdapter + bitable_cells 规范解析，模式与 finished_data 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.warehouse.bitable_cells import cell_text
from app.modules.warehouse.finished_data import cell_date, cell_qty, fetch_all_records

# 领料台账拉取字段（「物料名称(API)」为 C 期 API 文本列，优先；「物料名称」
# 为 Base 人工单选列，选项集可能缺新物料 → 名称取 API 列回落）
MATERIAL_OUTBOUND_FIELDS = [
    "物料名称(API)", "物料名称", "出库数量", "领用部门", "领用日期",
]


@dataclass(frozen=True)
class PickingRow:
    """领料行（已解析）。"""

    record_id: str
    usage_date: date | None
    material_name: str
    qty: float | None
    department: str


def _parse_picking_row(raw: dict[str, Any]) -> PickingRow:
    fields = raw.get("fields") or {}
    name = cell_text(fields.get("物料名称(API)")).strip()
    if not name:
        name = cell_text(fields.get("物料名称")).strip()
    return PickingRow(
        record_id=str(raw.get("record_id") or ""),
        usage_date=cell_date(fields.get("领用日期")),
        material_name=name,
        qty=cell_qty(fields.get("出库数量")),
        department=cell_text(fields.get("领用部门")).strip(),
    )


async def fetch_picking_rows(adapter: Any) -> list[PickingRow]:
    """全量拉取领料台账行（窗口过滤由调用方本地做；量级 <万行，安全）。"""
    rows = await fetch_all_records(adapter, "material_outbound", MATERIAL_OUTBOUND_FIELDS)
    return [_parse_picking_row(r) for r in rows]


@dataclass(frozen=True)
class DeptUsage:
    """某领用部门的窗口期用量聚合。"""

    department: str
    total_qty: float = 0.0
    order_count: int = 0
    top_materials: list[tuple[str, float]] = field(default_factory=list)


def summarize_dept_usage(
    rows: list[PickingRow], *, start: date, end: date
) -> list[DeptUsage]:
    """按领用部门聚合窗口期（含头不含尾）领料，用量降序、部门内物料 Top3。"""
    departments: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        if row.usage_date is None or not (start <= row.usage_date < end):
            continue
        dept = row.department or "未填部门"
        qty = row.qty or 0.0
        material = row.material_name or "未填物料"
        buckets = departments.setdefault(dept, {})
        buckets[material] = buckets.get(material, 0.0) + qty
        counts[dept] = counts.get(dept, 0) + 1
    result = [
        DeptUsage(
            department=dept,
            total_qty=sum(by_material.values()),
            order_count=counts[dept],
            top_materials=sorted(
                by_material.items(), key=lambda kv: kv[1], reverse=True
            )[:3],
        )
        for dept, by_material in departments.items()
    ]
    result.sort(key=lambda d: d.total_qty, reverse=True)
    return result
