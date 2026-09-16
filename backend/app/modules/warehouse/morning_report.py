"""每日晨报（分期C Ticket 03）：聚合异常/建议/昨日出入库，08:00 定时生成。

窗口守卫（08:00-09:00 北京时间）防 FIXED_TIME 重启误触发，
模式对齐 snapshot/intelligence 既有任务。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.intelligence import (
    get_rule_threshold,
)
from app.modules.warehouse.models import (
    WarehouseAlertRecord,
    WarehouseDailyBriefing,
    WarehouseMovement,
    WarehouseReplenishmentSuggestion,
    WarehouseStock,
)

CN_TZ = ZoneInfo("Asia/Shanghai")

_BRIEFING_WINDOW_START_HOUR = 8
_BRIEFING_WINDOW_END_HOUR = 9


def is_in_briefing_window(now_cn: datetime) -> bool:
    """北京时间 now 是否处于晨报执行窗口（08:00-09:00，含头不含尾）。"""
    return _BRIEFING_WINDOW_START_HOUR <= now_cn.hour < _BRIEFING_WINDOW_END_HOUR


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=CN_TZ)
    return start, start + timedelta(days=1)


async def list_briefings(db: AsyncSession, limit: int = 30) -> list[WarehouseDailyBriefing]:
    stmt = (
        select(WarehouseDailyBriefing)
        .where(WarehouseDailyBriefing.is_deleted == False)  # noqa: E712
        .order_by(WarehouseDailyBriefing.brief_date.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_briefing(db: AsyncSession, brief_date: date) -> WarehouseDailyBriefing | None:
    stmt = select(WarehouseDailyBriefing).where(
        WarehouseDailyBriefing.brief_date == brief_date,
        WarehouseDailyBriefing.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def generate_morning_report(db: AsyncSession, brief_date: date) -> dict[str, Any]:
    """生成（或覆盖）指定日期的晨报，返回 content 字典。"""
    today = datetime.now(CN_TZ).date()
    yesterday = brief_date - timedelta(days=1)
    y_start, y_end = _day_bounds(yesterday)

    async def _mv_stats(direction: str) -> dict[str, float]:
        stmt = (
            select(
                func.count().label("cnt"),
                func.coalesce(func.sum(WarehouseMovement.quantity), 0).label("qty"),
            ).where(
                WarehouseMovement.is_deleted == False,  # noqa: E712
                WarehouseMovement.direction == direction,
                WarehouseMovement.occurred_at >= y_start,
                WarehouseMovement.occurred_at < y_end,
            )
        )
        row = (await db.execute(stmt)).one()
        return {"count": int(row.cnt), "qty": float(row.qty)}

    yesterday_in = await _mv_stats("inbound")
    yesterday_out = await _mv_stats("outbound")

    # 异常 open 分类计数
    alert_rows = (
        await db.execute(
            select(WarehouseAlertRecord.rule_key, func.count())
            .where(
                WarehouseAlertRecord.status == "open",
                WarehouseAlertRecord.is_deleted == False,  # noqa: E712
            )
            .group_by(WarehouseAlertRecord.rule_key)
        )
    ).all()
    alerts = {r[0]: int(r[1]) for r in alert_rows}
    alerts_open_total = sum(alerts.values())

    # 补货建议 pending 数
    pending_suggestions = int(
        (
            await db.execute(
                select(func.count())
                .select_from(WarehouseReplenishmentSuggestion)
                .where(
                    WarehouseReplenishmentSuggestion.status == "pending",
                    WarehouseReplenishmentSuggestion.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one()
    )

    # 低库存 Top5（低于安全库存，按缺口升序=最接近的先；此处按缺口最大排）
    stock_rows = (
        await db.execute(
            select(WarehouseStock).where(
                WarehouseStock.is_deleted == False,  # noqa: E712
                WarehouseStock.quantity > 0,
            )
        )
    ).scalars().all()
    totals: dict[object, float] = {}
    materials: dict[object, WarehouseStock] = {}
    for s in stock_rows:
        totals[s.material_id] = totals.get(s.material_id, 0.0) + float(s.quantity)
        materials.setdefault(s.material_id, s)

    # 取安全库存信息（物料的 safety_stock 在物料表上；直接从物料查询）
    from app.modules.warehouse.models import WarehouseMaterial

    low_stock: list[dict[str, Any]] = []
    seen_materials = {
        mid: (await db.execute(
            select(WarehouseMaterial).where(WarehouseMaterial.id == mid)
        )).scalar_one()
        for mid in totals
    }
    expiry_days = int((await get_rule_threshold(db, "expiry", {"days": 30}))["days"])
    expiry_deadline = today + timedelta(days=expiry_days)
    for mid, qty in totals.items():
        m = seen_materials.get(mid)
        if m is None or m.safety_stock is None or m.safety_stock <= 0:
            continue
        if qty < float(m.safety_stock):
            low_stock.append(
                {"material_code": m.code, "material_name": m.name,
                 "total_quantity": qty, "safety_stock": float(m.safety_stock)}
            )
    low_stock.sort(key=lambda x: x["total_quantity"] - x["safety_stock"])

    # 临期 Top5（批次效期在阈值内）
    expiring: list[dict[str, Any]] = []
    for s in stock_rows:
        if s.expiry_date is None or s.quantity <= 0:
            continue
        days_left = (s.expiry_date - today).days
        if days_left <= expiry_days:
            expiring.append(
                {"material_name": s.material_name, "batch_no": s.batch_no,
                 "expiry_date": s.expiry_date.isoformat(), "days_left": days_left,
                 "quantity": float(s.quantity)}
            )
    expiring.sort(key=lambda x: x["days_left"])

    content = {
        "brief_date": brief_date.isoformat(),
        "yesterday": {
            "inbound_count": yesterday_in["count"],
            "inbound_qty": yesterday_in["qty"],
            "outbound_count": yesterday_out["count"],
            "outbound_qty": yesterday_out["qty"],
        },
        "alerts": {"open_total": alerts_open_total, "by_rule": alerts},
        "pending_suggestions": pending_suggestions,
        "low_stock_top5": low_stock[:5],
        "expiring_top5": expiring[:5],
    }

    # 幂等覆盖（同日唯一）
    existing_stmt = select(WarehouseDailyBriefing).where(
        WarehouseDailyBriefing.brief_date == brief_date,
        WarehouseDailyBriefing.is_deleted == False,  # noqa: E712
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        existing.content = content
    else:
        db.add(WarehouseDailyBriefing(brief_date=brief_date, content=content))
    await db.flush()
    return content
