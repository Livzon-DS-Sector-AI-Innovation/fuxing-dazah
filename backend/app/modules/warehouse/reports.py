"""报表中心聚合服务（分期C）：月报/周转率/消耗排名/库存报表 + Excel 导出。

口径统一走北京时间业务日；报表实时聚合不落库。
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.intelligence import (
    _material_stock_totals,  # type: ignore[attr-defined]  # noqa: F401 — 同包内部复用
)
from app.modules.warehouse.models import WarehouseMovement, WarehouseStock

CN_TZ = ZoneInfo("Asia/Shanghai")


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=CN_TZ)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(next_year, next_month, 1, tzinfo=CN_TZ)
    return start, end


async def get_monthly_report(db: AsyncSession, year: int, month: int) -> dict[str, Any]:
    """出入库月报：自然月聚合（北京时间），汇总 + 按物料明细。"""
    start, end = _month_bounds(year, month)
    rows = list(
        (
            await db.execute(
                select(WarehouseMovement).where(
                    WarehouseMovement.is_deleted == False,  # noqa: E712
                    WarehouseMovement.occurred_at >= start,
                    WarehouseMovement.occurred_at < end,
                )
            )
        ).scalars().all()
    )

    summary: dict[str, Any] = {
        "inbound_count": 0, "inbound_qty": 0.0,
        "outbound_count": 0, "outbound_qty": 0.0,
    }
    items: dict[tuple[str, str, str], dict[str, Any]] = {}
    for mv in rows:
        key = (mv.material_code, mv.material_name, mv.unit)
        item = items.setdefault(
            key,
            {"material_code": mv.material_code, "material_name": mv.material_name,
             "unit": mv.unit, "inbound_qty": 0.0, "outbound_qty": 0.0},
        )
        summary[f"{mv.direction}_count"] = summary.get(f"{mv.direction}_count", 0) + 1
        summary[f"{mv.direction}_qty"] = summary.get(f"{mv.direction}_qty", 0.0) + float(mv.quantity)
        item[f"{mv.direction}_qty"] = item.get(f"{mv.direction}_qty", 0.0) + float(mv.quantity)

    return {
        "year": year, "month": month, "summary": summary,
        "items": sorted(items.values(), key=lambda x: x["material_code"]),
    }


def build_monthly_xlsx(report: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "汇总"
    ws.append(["年份", "月份", "入库笔数", "入库数量", "出库笔数", "出库数量"])
    s = report["summary"]
    ws.append([report["year"], report["month"], s["inbound_count"], s["inbound_qty"],
               s["outbound_count"], s["outbound_qty"]])
    ws2 = wb.create_sheet("物料明细")
    ws2.append(["物料编码", "物料名称", "单位", "入库数量", "出库数量"])
    for item in report["items"]:
        ws2.append([item["material_code"], item["material_name"], item["unit"],
                    item["inbound_qty"], item["outbound_qty"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_table_xlsx(title: str, headers: list[str], rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def get_consumption_ranking(db: AsyncSession, days: int, limit: int) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    stmt = (
        select(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            WarehouseMovement.unit,
            func.sum(WarehouseMovement.quantity).label("outbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "outbound",
            WarehouseMovement.occurred_at >= start,
        )
        .group_by(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            WarehouseMovement.unit,
        )
        .order_by(func.sum(WarehouseMovement.quantity).desc())
        .limit(limit)
    )
    return [
        {"material_code": r.material_code, "material_name": r.material_name,
         "unit": r.unit, "outbound_qty": float(r.outbound)}
        for r in (await db.execute(stmt)).all()
    ]


async def get_turnover_ranking(
    db: AsyncSession, days: int, limit: int, order: str
) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    out_stmt = (
        select(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            func.sum(WarehouseMovement.quantity).label("outbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "outbound",
            WarehouseMovement.occurred_at >= start,
        )
        .group_by(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
        )
    )
    stock_map = {mid: row["total_quantity"] for mid, row in (await _material_stock_totals(db)).items()}
    ranking: list[dict[str, Any]] = []
    for r in (await db.execute(out_stmt)).all():
        stock = float(stock_map.get(r.material_id, 0.0))
        outbound = float(r.outbound)
        turnover = outbound / stock if stock > 0 else None
        ranking.append(
            {"material_code": r.material_code, "material_name": r.material_name,
             "outbound_qty": outbound, "current_stock": stock, "turnover": turnover}
        )
    has_value = [x for x in ranking if x["turnover"] is not None]
    none_value = [x for x in ranking if x["turnover"] is None]
    has_value.sort(key=lambda x: x["turnover"] or 0, reverse=(order == "desc"))
    return none_value + has_value if order == "desc" else has_value + none_value


async def get_stock_report(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[WarehouseStock], int]:
    stmt = select(WarehouseStock).where(
        WarehouseStock.is_deleted == False,  # noqa: E712
        WarehouseStock.quantity != 0,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    stmt = (
        stmt.order_by(WarehouseStock.material_code, WarehouseStock.batch_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


# ── 库位地图（分期D Ticket 02） ──


async def get_location_map(db: AsyncSession) -> list[dict[str, Any]]:
    """按 zone→aisle 分组返回库位与占用信息（库位地图数据源）。"""
    from app.modules.warehouse.models import WarehouseLocation

    stmt = (
        select(WarehouseLocation)
        .where(WarehouseLocation.is_deleted == False)  # noqa: E712
        .order_by(WarehouseLocation.zone, WarehouseLocation.aisle, WarehouseLocation.code)
    )
    locations = list((await db.execute(stmt)).scalars().all())

    stock_stmt = (
        select(
            WarehouseStock.location_id,
            func.count().label("rows"),
            func.coalesce(func.sum(WarehouseStock.quantity), 0).label("qty"),
        )
        .where(WarehouseStock.is_deleted == False, WarehouseStock.quantity > 0)  # noqa: E712
        .group_by(WarehouseStock.location_id)
    )
    occupancy = {
        r[0]: {"rows": int(r[1]), "qty": float(r[2])}
        for r in (await db.execute(stock_stmt)).all()
    }

    return [
        {
            "id": str(loc.id),
            "code": loc.code,
            "name": loc.name,
            "zone": loc.zone or "未分区",
            "aisle": loc.aisle or "-",
            "location_type": loc.location_type,
            "occupied_rows": occupancy.get(loc.id, {}).get("rows", 0),
            "total_qty": occupancy.get(loc.id, {}).get("qty", 0.0),
        }
        for loc in locations
    ]


async def get_batch_trace(
    db: AsyncSession, *, material_code: str, batch_no: str
) -> dict[str, Any]:
    """从批次出发的正查（出库去向）+ 反查（入库来源）完整流水。"""
    stmt = (
        select(WarehouseMovement)
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.material_code == material_code,
            WarehouseMovement.batch_no == batch_no,
        )
        .order_by(WarehouseMovement.occurred_at.desc())
    )
    movements = list((await db.execute(stmt)).scalars().all())
    inbound_flows = []
    outbound_flows = []
    for mv in movements:
        flow = {
            "movement_no": mv.movement_no,
            "direction": mv.direction,
            "source_type": mv.source_type,
            "quantity": float(mv.quantity),
            "unit": mv.unit,
            "location_name": mv.location_name,
            "occurred_at": mv.occurred_at.isoformat() if mv.occurred_at else None,
            "remark": mv.remark,
        }
        if mv.direction == "inbound":
            inbound_flows.append(flow)
        elif mv.direction == "outbound":
            outbound_flows.append(flow)
    return {
        "material_code": material_code,
        "batch_no": batch_no,
        "inbound_flows": inbound_flows,
        "outbound_flows": outbound_flows,
    }


def build_batch_trace_xlsx(trace: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "批次追溯"
    ws.append(["方向", "单号", "发生时间", "数量", "单位", "库位", "来源/去向", "备注"])
    for flow in trace["inbound_flows"] + trace["outbound_flows"]:
        ws.append([
            flow["direction"], flow["movement_no"],
            flow["occurred_at"][:19] if flow["occurred_at"] else "",
            flow["quantity"], flow["unit"], flow["location_name"],
            flow["source_type"], flow["remark"] or "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
