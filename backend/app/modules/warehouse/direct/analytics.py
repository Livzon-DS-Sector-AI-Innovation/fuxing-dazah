"""直读聚合层——概览/驾驶舱口径从 view 列表现算（键与镜像版逐键对齐）。

差异口径（诚实返回，不造数）：
- total_quantity_change：镜像版来自本地日快照环比——直读口径无快照，恒 None
  （前端已兼容 None）；
- low_stock：Base 无安全库存基准列 → 恒空列表（count=0）；
- by_location_type：库位是本地概念，直读无源 → 空列表；
- 盘点/QC 待办：本地业务数据，仍查本地库（db 入参）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.direct.views import MovementView, StockView

CN_TZ = ZoneInfo("Asia/Shanghai")
IDLE_DAYS = 90  # 与 dashboard.get_low_stock_top 呆滞口径一致


def _f(value: float) -> float:
    return round(float(value), 4)


def _day_bounds_cn(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=CN_TZ)
    return start, start + timedelta(days=1)


def _to_cn(dt: datetime) -> datetime:
    return dt.astimezone(CN_TZ) if dt.tzinfo else dt.replace(tzinfo=UTC).astimezone(CN_TZ)


def _stock_totals_by_code(stocks: list[StockView]) -> dict[str, float]:
    """按代码聚合库存（出入库名称可能带规格后缀与库存名不一致——
    镜像版按 material_id 聚合，直读版等价物即代码）。"""
    totals: dict[str, float] = {}
    for s in stocks:
        if s.code:
            totals[s.code] = totals.get(s.code, 0.0) + s.quantity
    return totals


def _movement_stats(
    movements: list[MovementView], start: datetime, end: datetime
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {
        "inbound": {"count": 0, "quantity": 0.0},
        "outbound": {"count": 0, "quantity": 0.0},
    }
    for m in movements:
        if start <= m.occurred_at < end:
            slot = stats.get(m.direction)
            if slot is not None:
                slot["count"] += 1
                slot["quantity"] += m.quantity
    for slot in stats.values():
        slot["quantity"] = _f(slot["quantity"])
    return stats


async def overview(
    stocks: list[StockView], movements: list[MovementView],
    material_count: int, db: AsyncSession,
) -> dict[str, Any]:
    from app.modules.warehouse.models import WarehouseLocation

    today = datetime.now(CN_TZ).date()
    start, end = _day_bounds_cn(today)
    stats = _movement_stats(movements, start, end)
    location_count = (
        await db.execute(
            select(func.count()).select_from(WarehouseLocation).where(
                WarehouseLocation.is_deleted.is_(False)
            )
        )
    ).scalar_one()
    return {
        "material_count": material_count,
        "location_count": int(location_count),
        "stock_sku_count": len(stocks),
        "low_stock_materials": [],  # Base 无安全库存基准列
        "today_inbound_quantity": stats["inbound"]["quantity"],
        "today_outbound_quantity": stats["outbound"]["quantity"],
    }


async def summary(
    stocks: list[StockView], movements: list[MovementView],
    material_count: int, db: AsyncSession,
) -> dict[str, Any]:
    from app.modules.warehouse.models import WarehouseStocktake

    today = datetime.now(CN_TZ).date()
    today_start, today_end = _day_bounds_cn(today)
    yesterday_start, _ = _day_bounds_cn(today - timedelta(days=1))
    today_stats = _movement_stats(movements, today_start, today_end)
    yesterday_stats = _movement_stats(movements, yesterday_start, today_start)
    draft_count = (
        await db.execute(
            select(func.count()).select_from(WarehouseStocktake).where(
                WarehouseStocktake.status == "draft",
                WarehouseStocktake.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    today_in = today_stats["inbound"]
    today_out = today_stats["outbound"]
    summary_text = (
        f"今日入库 {today_in['count']} 笔共 {today_in['quantity']:g}，"
        f"出库 {today_out['count']} 笔共 {today_out['quantity']:g}；"
        f"低库存 0 项；进行中盘点 {int(draft_count)} 张。"
    )
    return {
        "total_quantity": _f(sum(s.quantity for s in stocks)),
        "total_quantity_change": None,  # 环比属本地快照体系，直读口径无源
        "material_count": material_count,
        "stock_sku_count": len(stocks),
        "today_inbound_quantity": today_in["quantity"],
        "today_inbound_count": today_in["count"],
        "today_outbound_quantity": today_out["quantity"],
        "today_outbound_count": today_out["count"],
        "yesterday_inbound_quantity": yesterday_stats["inbound"]["quantity"],
        "yesterday_outbound_quantity": yesterday_stats["outbound"]["quantity"],
        "low_stock_count": 0,
        "draft_stocktake_count": int(draft_count),
        "summary_text": summary_text,
    }


def movement_trend(
    movements: list[MovementView], days: int
) -> list[dict[str, Any]]:
    today = datetime.now(CN_TZ).date()
    start_day = today - timedelta(days=days - 1)
    start_dt = _day_bounds_cn(start_day)[0]
    end_dt = _day_bounds_cn(today)[1]
    by_day: dict[date, dict[str, float]] = {}
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        by_day[day] = {"inbound": 0.0, "outbound": 0.0}
    for m in movements:
        if start_dt <= m.occurred_at < end_dt:
            day = _to_cn(m.occurred_at).date()
            slot = by_day.get(day)
            if slot is not None and m.direction in slot:
                slot[m.direction] += m.quantity
    return [
        {
            "date": day.strftime("%Y-%m-%d"),
            "inbound": _f(slot["inbound"]),
            "outbound": _f(slot["outbound"]),
        }
        for day, slot in sorted(by_day.items())
    ]


def stock_distribution(stocks: list[StockView]) -> dict[str, Any]:
    by_category: dict[str, float] = {}
    for s in stocks:
        by_category[s.category] = by_category.get(s.category, 0.0) + s.quantity
    return {
        "by_category": [
            {"category": cat, "total_quantity": _f(qty)}
            for cat, qty in sorted(
                by_category.items(), key=lambda kv: -kv[1]
            )
        ],
        "by_location_type": [],  # 库位是本地概念，直读无源
    }


def low_stock_top(
    stocks: list[StockView], movements: list[MovementView], limit: int
) -> dict[str, Any]:
    totals = _stock_totals_by_code(stocks)
    names_by_code: dict[str, str] = {s.code: s.name for s in stocks if s.code}
    last_inbound: dict[str, datetime] = {}
    for m in movements:
        if m.direction != "inbound" or not m.code:
            continue
        if m.code not in last_inbound or m.occurred_at > last_inbound[m.code]:
            last_inbound[m.code] = m.occurred_at
    now_cn = datetime.now(CN_TZ)
    idle: list[dict[str, Any]] = []
    for code, qty in totals.items():
        if qty <= 0:
            continue
        last = last_inbound.get(code)
        if last is None:
            continue
        days_idle = (now_cn.date() - _to_cn(last).date()).days
        if days_idle >= IDLE_DAYS:
            idle.append({
                "material_code": code,
                "material_name": names_by_code.get(code, code),
                "total_quantity": _f(qty),
                "days_idle": days_idle,
                "last_inbound_at": _to_cn(last).isoformat(),
            })
    idle.sort(key=lambda x: -x["days_idle"])
    return {"low_stock": [], "idle": idle[:limit]}  # 安全库存无源 → low 恒空


async def todos(
    stocks: list[StockView], movements: list[MovementView], db: AsyncSession
) -> dict[str, Any]:
    from app.modules.warehouse.dashboard import _qc_pending
    from app.modules.warehouse.models import WarehouseStocktake

    draft_stocktakes = [
        {
            "stocktake_no": st.stocktake_no,
            "remark": st.remark,
            "created_at": st.created_at.isoformat() if st.created_at else None,
        }
        for st in (
            await db.execute(
                select(WarehouseStocktake)
                .where(
                    WarehouseStocktake.status == "draft",
                    WarehouseStocktake.is_deleted.is_(False),
                )
                .order_by(WarehouseStocktake.created_at.desc())
                .limit(5)
            )
        ).scalars()
    ]
    recent_movements = [
        {
            "movement_no": _movement_no_of(m),
            "direction": m.direction,
            "material_name": m.name,
            "quantity": _f(m.quantity),
            "unit": m.unit,
            "occurred_at": _to_cn(m.occurred_at).isoformat(),
        }
        for m in movements[:5]  # reader 已按时间倒序
    ]
    return {
        "low_stock_count": 0,
        "low_stock_items": [],
        "draft_stocktakes": draft_stocktakes,
        "recent_movements": recent_movements,
        "qc_pending": await _qc_pending(db),
    }


def _movement_no_of(m: MovementView) -> str:
    prefix = "RCPT" if m.direction == "inbound" else "OTB"
    return f"{prefix}-{m.record_id[:16]}"


# ── 报表族（T4）────────────────────────────────────────────────

def _month_bounds_cn(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=CN_TZ)
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime(end_year, end_month, 1, tzinfo=CN_TZ)


def monthly_report(
    movements: list[MovementView], year: int, month: int
) -> dict[str, Any]:
    start, end = _month_bounds_cn(year, month)
    summary: dict[str, Any] = {
        "inbound_count": 0, "inbound_qty": 0.0,
        "outbound_count": 0, "outbound_qty": 0.0,
    }
    items: dict[tuple[str, str, str], dict[str, Any]] = {}
    for mv in movements:
        if not (start <= mv.occurred_at < end):
            continue
        key = (mv.code, mv.name, mv.unit)
        item = items.setdefault(key, {
            "material_code": mv.code, "material_name": mv.name,
            "unit": mv.unit, "inbound_qty": 0.0, "outbound_qty": 0.0,
        })
        summary[f"{mv.direction}_count"] = summary.get(f"{mv.direction}_count", 0) + 1
        summary[f"{mv.direction}_qty"] = summary.get(f"{mv.direction}_qty", 0.0) + mv.quantity
        item[f"{mv.direction}_qty"] = item.get(f"{mv.direction}_qty", 0.0) + mv.quantity
    summary = {k: (_f(v) if k.endswith("_qty") else v) for k, v in summary.items()}
    for it in items.values():
        it["inbound_qty"] = _f(it["inbound_qty"])
        it["outbound_qty"] = _f(it["outbound_qty"])
    return {
        "year": year, "month": month, "summary": summary,
        "items": sorted(items.values(), key=lambda x: x["material_code"]),
    }


def annual_report(
    movements: list[MovementView], year: int
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "inbound_count": 0, "inbound_qty": 0.0,
        "outbound_count": 0, "outbound_qty": 0.0,
    }
    months: list[dict[str, Any]] = []
    items: dict[tuple[str, str, str], dict[str, Any]] = {}
    for month in range(1, 13):
        report = monthly_report(movements, year, month)
        s = report["summary"]
        months.append({
            "month": month,
            "inbound_qty": s["inbound_qty"],
            "outbound_qty": s["outbound_qty"],
        })
        for key in summary:
            summary[key] += s[key]
        for item in report["items"]:
            mkey = (item["material_code"], item["material_name"], item["unit"])
            acc = items.setdefault(mkey, {
                "material_code": item["material_code"],
                "material_name": item["material_name"], "unit": item["unit"],
                "inbound_qty": 0.0, "outbound_qty": 0.0,
            })
            acc["inbound_qty"] += item["inbound_qty"]
            acc["outbound_qty"] += item["outbound_qty"]
    return {
        "year": year, "summary": summary, "months": months,
        "items": sorted(items.values(), key=lambda x: x["outbound_qty"], reverse=True),
    }


def turnover_ranking(
    stocks: list[StockView], movements: list[MovementView],
    days: int, limit: int, order: str = "desc",
) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    outbound: dict[str, float] = {}
    names: dict[str, str] = {}
    for mv in movements:
        if mv.direction == "outbound" and mv.occurred_at >= start and mv.code:
            outbound[mv.code] = outbound.get(mv.code, 0.0) + mv.quantity
            names[mv.code] = mv.name
    stock_map = _stock_totals_by_code(stocks)
    ranking: list[dict[str, Any]] = []
    for code, out_qty in outbound.items():
        stock = stock_map.get(code, 0.0)
        turnover = out_qty / stock if stock > 0 else None
        ranking.append({
            "material_code": code, "material_name": names.get(code, code),
            "outbound_qty": _f(out_qty), "current_stock": _f(stock),
            "turnover": round(turnover, 4) if turnover is not None else None,
        })
    reverse = order != "asc"
    has_value = [x for x in ranking if x["turnover"] is not None]
    none_value = [x for x in ranking if x["turnover"] is None]
    has_value.sort(key=lambda x: x["turnover"], reverse=reverse)  # type: ignore[arg-type,return-value]
    return (has_value + none_value)[:limit]


def consumption_ranking(
    movements: list[MovementView], days: int, limit: int
) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    totals: dict[tuple[str, str, str], float] = {}
    for mv in movements:
        if mv.direction == "outbound" and mv.occurred_at >= start:
            key = (mv.code, mv.name, mv.unit)
            totals[key] = totals.get(key, 0.0) + mv.quantity
    rows = [
        {"material_code": k[0], "material_name": k[1], "unit": k[2],
         "outbound_qty": _f(v)}
        for k, v in totals.items()
    ]
    rows.sort(key=lambda x: -x["outbound_qty"])
    return rows[:limit]


def stock_report_rows(
    stocks: list[StockView], page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    rows = [
        {
            "material_code": s.code, "material_name": s.name,
            "batch_no": s.batch_no, "location_name": "",
            "expiry_date": s.expiry_date.isoformat() if s.expiry_date else None,
            "quantity": s.quantity,
        }
        for s in stocks if s.quantity != 0
    ]
    rows.sort(key=lambda r: (r["material_code"], r["batch_no"]))
    start = (page - 1) * page_size
    return rows[start : start + page_size], len(rows)


def batch_trace(
    movements: list[MovementView], material_code: str, batch_no: str
) -> dict[str, Any]:
    matched = sorted(
        (m for m in movements
         if m.code == material_code and m.batch_no == batch_no),
        key=lambda m: m.occurred_at, reverse=True,
    )
    inbound_flows: list[dict[str, Any]] = []
    outbound_flows: list[dict[str, Any]] = []
    for mv in matched:
        flow = {
            "movement_no": _movement_no_of(mv),
            "direction": mv.direction,
            "source_type": mv.source_type,
            "quantity": mv.quantity,
            "unit": mv.unit,
            "location_name": "",
            "occurred_at": mv.occurred_at.isoformat(),
            "remark": None,
        }
        (inbound_flows if mv.direction == "inbound" else outbound_flows).append(flow)
    return {
        "material_code": material_code, "batch_no": batch_no,
        "inbound_flows": inbound_flows, "outbound_flows": outbound_flows,
    }
