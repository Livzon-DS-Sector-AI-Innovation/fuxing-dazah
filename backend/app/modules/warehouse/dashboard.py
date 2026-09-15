"""驾驶舱聚合服务：只读聚合查询，一次取数供前端驾驶舱各区块渲染。

口径约定：
- 库存总量/分布：仅 is_deleted=false 的库存行；
- 出入库按北京时间业务日聚合（occurred_at 为 timestamptz）；
- 环比基于日快照（compare 最近一个早于今日的快照日），快照缺失返回 None；
- 呆滞：有库存且最近一次入库（无入库流水则取物料创建时间）距今 >= 90 天。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStockDailySnapshot,
    WarehouseStocktake,
)

CN_TZ = ZoneInfo("Asia/Shanghai")
IDLE_DAYS = 90


def _cn_date_expr() -> Any:
    """occurred_at 的北京时间业务日（date）。"""
    return func.date(func.timezone("Asia/Shanghai", WarehouseMovement.occurred_at))


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=CN_TZ)
    return start, start + timedelta(days=1)


def _f(value: Any) -> float:
    return float(value or 0)


async def _movement_stats(
    db: AsyncSession, start: datetime, end: datetime
) -> dict[str, dict[str, float]]:
    """[start, end) 窗口内按方向聚合 {direction: {"count": n, "quantity": q}}。"""
    stmt = (
        select(
            WarehouseMovement.direction,
            func.count().label("cnt"),
            func.sum(WarehouseMovement.quantity).label("qty"),
        )
        .where(
            WarehouseMovement.is_deleted.is_(False),
            WarehouseMovement.occurred_at >= start,
            WarehouseMovement.occurred_at < end,
        )
        .group_by(WarehouseMovement.direction)
    )
    result = await db.execute(stmt)
    return {
        row.direction: {"count": int(row.cnt), "quantity": _f(row.qty)}
        for row in result.all()
    }


async def _material_stock_totals(db: AsyncSession) -> dict[Any, dict[str, Any]]:
    """{material_id: {code, name, category, safety_stock, created_at, total_quantity}}。"""
    stmt = (
        select(
            WarehouseMaterial.id,
            WarehouseMaterial.code,
            WarehouseMaterial.name,
            WarehouseMaterial.category,
            WarehouseMaterial.safety_stock,
            WarehouseMaterial.created_at,
            func.coalesce(func.sum(WarehouseStock.quantity), 0).label("total_quantity"),
        )
        .join(WarehouseStock, WarehouseStock.material_id == WarehouseMaterial.id)
        .where(
            WarehouseMaterial.is_deleted.is_(False),
            WarehouseStock.is_deleted.is_(False),
        )
        .group_by(
            WarehouseMaterial.id,
            WarehouseMaterial.code,
            WarehouseMaterial.name,
            WarehouseMaterial.category,
            WarehouseMaterial.safety_stock,
            WarehouseMaterial.created_at,
        )
    )
    result = await db.execute(stmt)
    return {
        row.id: {
            "code": row.code,
            "name": row.name,
            "category": row.category,
            "safety_stock": row.safety_stock,
            "created_at": row.created_at,
            "total_quantity": _f(row.total_quantity),
        }
        for row in result.all()
    }


async def _low_stock_items(db: AsyncSession) -> list[dict[str, Any]]:
    totals = await _material_stock_totals(db)
    items: list[dict[str, Any]] = []
    for row in totals.values():
        safety = row["safety_stock"]
        if safety is not None and safety > 0 and row["total_quantity"] < float(safety):
            items.append(
                {
                    "material_code": row["code"],
                    "material_name": row["name"],
                    "total_quantity": row["total_quantity"],
                    "safety_stock": float(safety),
                }
            )
    items.sort(key=lambda x: x["total_quantity"] - x["safety_stock"])
    return items


async def get_summary(db: AsyncSession) -> dict[str, Any]:
    today = datetime.now(CN_TZ).date()
    today_start, today_end = _day_bounds(today)
    yesterday_start, _ = _day_bounds(today - timedelta(days=1))

    stock_stmt = select(
        func.coalesce(func.sum(WarehouseStock.quantity), 0).label("total"),
        func.count().label("rows"),
        func.count(func.distinct(WarehouseStock.material_id)).label("materials"),
    ).where(WarehouseStock.is_deleted.is_(False))
    stock_row = (await db.execute(stock_stmt)).one()

    material_count_stmt = (
        select(func.count()).select_from(WarehouseMaterial).where(WarehouseMaterial.is_deleted.is_(False))
    )
    material_count = (await db.execute(material_count_stmt)).scalar_one()

    today_stats = await _movement_stats(db, today_start, today_end)
    yesterday_stats = await _movement_stats(db, yesterday_start, today_start)

    # 环比：今日快照 vs 最近一个早于今日的快照日（两者任一缺失则返回 None）
    prev_date_stmt = select(func.max(WarehouseStockDailySnapshot.snapshot_date)).where(
        WarehouseStockDailySnapshot.snapshot_date < today,
        WarehouseStockDailySnapshot.is_deleted.is_(False),
    )
    prev_date = (await db.execute(prev_date_stmt)).scalar_one_or_none()

    async def _snapshot_total(day: date) -> float | None:
        stmt = select(
            func.sum(WarehouseStockDailySnapshot.total_quantity)
        ).where(
            WarehouseStockDailySnapshot.snapshot_date == day,
            WarehouseStockDailySnapshot.is_deleted.is_(False),
        )
        value = (await db.execute(stmt)).scalar_one_or_none()
        return None if value is None else _f(value)

    total_quantity_change: float | None = None
    if prev_date is not None:
        today_snapshot = await _snapshot_total(today)
        prev_snapshot = await _snapshot_total(prev_date)
        if today_snapshot is not None and prev_snapshot is not None:
            total_quantity_change = round(today_snapshot - prev_snapshot, 4)

    low_items = await _low_stock_items(db)
    draft_count_stmt = (
        select(func.count())
        .select_from(WarehouseStocktake)
        .where(WarehouseStocktake.status == "draft", WarehouseStocktake.is_deleted.is_(False))
    )
    draft_count = (await db.execute(draft_count_stmt)).scalar_one()

    today_in = today_stats.get("inbound", {"count": 0, "quantity": 0.0})
    today_out = today_stats.get("outbound", {"count": 0, "quantity": 0.0})
    summary_text = (
        f"今日入库 {today_in['count']} 笔共 {today_in['quantity']:g}，"
        f"出库 {today_out['count']} 笔共 {today_out['quantity']:g}；"
        f"低库存 {len(low_items)} 项；进行中盘点 {draft_count} 张。"
    )

    return {
        "total_quantity": _f(stock_row.total),
        "total_quantity_change": total_quantity_change,
        "material_count": int(material_count),
        "stock_sku_count": int(stock_row.rows),
        "today_inbound_quantity": today_in["quantity"],
        "today_inbound_count": today_in["count"],
        "today_outbound_quantity": today_out["quantity"],
        "today_outbound_count": today_out["count"],
        "yesterday_inbound_quantity": yesterday_stats.get("inbound", {}).get("quantity", 0.0),
        "yesterday_outbound_quantity": yesterday_stats.get("outbound", {}).get("quantity", 0.0),
        "low_stock_count": len(low_items),
        "draft_stocktake_count": int(draft_count),
        "summary_text": summary_text,
    }


async def get_movement_trend(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    today = datetime.now(CN_TZ).date()
    start_day = today - timedelta(days=days - 1)
    start_dt, end_dt = _day_bounds(start_day)

    day_expr = _cn_date_expr()  # SELECT 与 GROUP BY 必须复用同一表达式（PG 按表达式文本匹配）
    stmt = (
        select(
            day_expr.label("day"),
            WarehouseMovement.direction,
            func.sum(WarehouseMovement.quantity).label("qty"),
        )
        .where(
            WarehouseMovement.is_deleted.is_(False),
            WarehouseMovement.occurred_at >= start_dt,
            WarehouseMovement.occurred_at < end_dt,
        )
        .group_by(day_expr, WarehouseMovement.direction)
    )
    by_day: dict[date, dict[str, float]] = {}
    for row in (await db.execute(stmt)).all():
        day = row.day if isinstance(row.day, date) else datetime.fromisoformat(str(row.day)).date()
        slot = by_day.setdefault(day, {"inbound": 0.0, "outbound": 0.0})
        if row.direction in ("inbound", "outbound"):
            slot[row.direction] = _f(row.qty)

    trend: list[dict[str, Any]] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        slot = by_day.get(day, {"inbound": 0.0, "outbound": 0.0})
        trend.append(
            {"date": day.strftime("%Y-%m-%d"), "inbound": slot["inbound"], "outbound": slot["outbound"]}
        )
    return trend


async def get_stock_distribution(db: AsyncSession) -> dict[str, Any]:
    by_category_stmt = (
        select(
            WarehouseMaterial.category.label("category"),
            func.coalesce(func.sum(WarehouseStock.quantity), 0).label("qty"),
        )
        .select_from(WarehouseStock)
        .join(WarehouseMaterial, WarehouseMaterial.id == WarehouseStock.material_id)
        .where(WarehouseStock.is_deleted.is_(False), WarehouseMaterial.is_deleted.is_(False))
        .group_by(WarehouseMaterial.category)
    )
    by_location_stmt = (
        select(
            WarehouseLocation.location_type.label("location_type"),
            func.coalesce(func.sum(WarehouseStock.quantity), 0).label("qty"),
        )
        .select_from(WarehouseStock)
        .join(WarehouseLocation, WarehouseLocation.id == WarehouseStock.location_id)
        .where(WarehouseStock.is_deleted.is_(False), WarehouseLocation.is_deleted.is_(False))
        .group_by(WarehouseLocation.location_type)
    )
    return {
        "by_category": [
            {"category": row.category, "total_quantity": _f(row.qty)}
            for row in (await db.execute(by_category_stmt)).all()
        ],
        "by_location_type": [
            {"location_type": row.location_type, "total_quantity": _f(row.qty)}
            for row in (await db.execute(by_location_stmt)).all()
        ],
    }


async def get_low_stock_top(db: AsyncSession, limit: int) -> dict[str, Any]:
    low_items = await _low_stock_items(db)

    totals = await _material_stock_totals(db)
    last_inbound_stmt = (
        select(
            WarehouseMovement.material_id,
            func.max(WarehouseMovement.occurred_at).label("last_inbound"),
        )
        .where(
            WarehouseMovement.is_deleted.is_(False),
            WarehouseMovement.direction == "inbound",
        )
        .group_by(WarehouseMovement.material_id)
    )
    last_inbound_map = {
        row.material_id: row.last_inbound for row in (await db.execute(last_inbound_stmt)).all()
    }

    now = datetime.now(CN_TZ)
    idle: list[dict[str, Any]] = []
    for material_id, row in totals.items():
        if row["total_quantity"] <= 0:
            continue
        last_in = last_inbound_map.get(material_id) or row["created_at"]
        if last_in is None:
            continue
        last_aware = last_in if last_in.tzinfo else last_in.replace(tzinfo=CN_TZ)
        days_idle = (now - last_aware.astimezone(CN_TZ)).days
        if days_idle >= IDLE_DAYS:
            idle.append(
                {
                    "material_code": row["code"],
                    "material_name": row["name"],
                    "total_quantity": row["total_quantity"],
                    "days_idle": days_idle,
                    "last_inbound_at": last_aware.astimezone(CN_TZ).isoformat(),
                }
            )
    idle.sort(key=lambda x: x["days_idle"], reverse=True)

    return {"low_stock": low_items[:limit], "idle": idle[:limit]}


async def get_todos(db: AsyncSession) -> dict[str, Any]:
    low_items = await _low_stock_items(db)

    draft_stmt = (
        select(WarehouseStocktake)
        .where(WarehouseStocktake.status == "draft", WarehouseStocktake.is_deleted.is_(False))
        .order_by(WarehouseStocktake.created_at.desc())
        .limit(5)
    )
    draft_stocktakes = [
        {
            "stocktake_no": st.stocktake_no,
            "remark": st.remark,
            "created_at": st.created_at.isoformat() if st.created_at else None,
        }
        for st in (await db.execute(draft_stmt)).scalars().all()
    ]

    recent_stmt = (
        select(WarehouseMovement)
        .where(WarehouseMovement.is_deleted.is_(False))
        .order_by(WarehouseMovement.occurred_at.desc())
        .limit(5)
    )
    recent_movements = [
        {
            "movement_no": mv.movement_no,
            "direction": mv.direction,
            "material_name": mv.material_name,
            "quantity": _f(mv.quantity),
            "unit": mv.unit,
            "occurred_at": mv.occurred_at.astimezone(CN_TZ).isoformat(),
        }
        for mv in (await db.execute(recent_stmt)).scalars().all()
    ]

    return {
        "low_stock_count": len(low_items),
        "low_stock_items": low_items[:5],
        "draft_stocktakes": draft_stocktakes,
        "recent_movements": recent_movements,
    }
