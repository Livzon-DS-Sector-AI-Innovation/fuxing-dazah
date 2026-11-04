"""库存分析定档（2026-11-04 直读改造）：从直读层取数 → 全量分析 → 按日落库。

- 数据源：direct 三域缓存（生产 Base 真实口径，不依赖镜像）；
- 幂等：同日重跑覆盖 summary（晨报同款，report_date 唯一部分索引）；
- 内容：KPI 总量/分布/周转与消耗 Top/预警（呆滞、临期、零库存）。
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehouseAnalysisReport

logger = logging.getLogger(__name__)
CN_TZ = ZoneInfo("Asia/Shanghai")

EXPIRY_WARN_DAYS = 90   # 临期预警窗口（与 intelligence 过期检测口径对齐取 90 天）
TOP_LIMIT = 10


def _expiry_batches(stocks: list, warn_days: int = EXPIRY_WARN_DAYS) -> list[dict[str, Any]]:
    """临期批次（效期在窗口内；已过期按剩余天数负值保留）。"""
    today = datetime.now(CN_TZ).date()
    batches: list[dict[str, Any]] = []
    for s in stocks:
        if s.expiry_date is None:
            continue
        days_left = (s.expiry_date - today).days
        if days_left <= warn_days:
            batches.append({
                "material_code": s.code, "material_name": s.name,
                "batch_no": s.batch_no,
                "expiry_date": s.expiry_date.isoformat(),
                "days_left": days_left,
            })
    batches.sort(key=lambda b: b["days_left"])
    return batches


async def build_analysis_summary() -> dict[str, Any]:
    """从直读三域缓存组装全量分析（不触 DB——预警计数也为直读口径）。"""
    from app.modules.warehouse.direct import analytics
    from app.modules.warehouse.direct.service import _load_views

    stocks, movements, material_count = await _load_views()
    by_code: dict[str, float] = {}
    names: dict[str, str] = {}
    status_count = {"normal": 0, "quarantine": 0, "frozen": 0}
    for s in stocks:
        if s.code:
            by_code[s.code] = by_code.get(s.code, 0.0) + s.quantity
            names[s.code] = s.name
        if s.status in status_count:
            status_count[s.status] += 1
    zero_stock = sum(1 for q in by_code.values() if q <= 0)
    top = analytics.low_stock_top(stocks, movements, TOP_LIMIT)
    expiry = _expiry_batches(stocks)
    return {
        "kpi": {
            "total_quantity": round(sum(s.quantity for s in stocks), 4),
            "stock_rows": len(stocks),
            "stock_skus": len(by_code),
            "material_count": material_count,
            "zero_stock_count": zero_stock,
            "frozen_count": status_count["frozen"],
            "quarantine_count": status_count["quarantine"],
        },
        "distribution": analytics.stock_distribution(stocks)["by_category"],
        "top": {
            "turnover": analytics.turnover_ranking(stocks, movements, 30, TOP_LIMIT),
            "consumption": analytics.consumption_ranking(movements, 30, TOP_LIMIT),
        },
        "alerts": {
            "low_stock_count": 0,  # Base 无安全库存基准列（口径同驾驶舱）
            "idle_count": len(top["idle"]),
            "idle": top["idle"],
            "expiry_count": len(expiry),
            "expiry": expiry[:50],
        },
    }


async def run_inventory_analysis(
    db: AsyncSession, *, trigger: str = "scheduled"
) -> WarehouseAnalysisReport:
    """生成（或覆盖）今日分析定档；调用方负责 commit。"""
    started = time.monotonic()
    report_date = datetime.now(CN_TZ).date()
    summary = await build_analysis_summary()
    row = (
        await db.execute(
            select(WarehouseAnalysisReport).where(
                WarehouseAnalysisReport.report_date == report_date,
                WarehouseAnalysisReport.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    duration_ms = round((time.monotonic() - started) * 1000)
    if row is None:
        row = WarehouseAnalysisReport(
            report_date=report_date, summary=summary,
            trigger=trigger, duration_ms=duration_ms,
        )
        db.add(row)
    else:
        row.summary = summary
        row.trigger = trigger
        row.duration_ms = duration_ms
    await db.flush()
    logger.info(
        "库存分析定档完成: date=%s trigger=%s skus=%s 耗时=%dms",
        report_date, trigger, summary["kpi"]["stock_skus"], duration_ms,
    )
    return row


async def get_latest_analysis(db: AsyncSession) -> WarehouseAnalysisReport | None:
    return (
        await db.execute(
            select(WarehouseAnalysisReport)
            .where(WarehouseAnalysisReport.is_deleted.is_(False))
            .order_by(WarehouseAnalysisReport.report_date.desc())
            .limit(1)
        )
    ).scalars().first()


async def list_analysis_reports(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[WarehouseAnalysisReport], int]:
    from sqlalchemy import func

    base = select(WarehouseAnalysisReport).where(
        WarehouseAnalysisReport.is_deleted.is_(False)
    )
    total = (
        await db.execute(
            select(func.count()).select_from(base.order_by(None).subquery())
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(WarehouseAnalysisReport.report_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total)
