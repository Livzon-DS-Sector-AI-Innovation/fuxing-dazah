"""仪表/探测器总览统计查询。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as time_today
from app.modules.meter.models import GasDetectorRecord, InstrumentRecord


async def get_instrument_overview(db: AsyncSession) -> dict[str, int]:
    """标准计量器具总览统计。"""
    from sqlalchemy import case

    today = time_today()

    # 子查询计算每条记录的有效状态
    # 在用/超期 + 已过期 → 超期；手动超期 + 未过期/无日期 → 在用
    status_expr = case(
        (
            InstrumentRecord.status.in_(["超期", "在用"])
            & (InstrumentRecord.next_calibration_date < today),
            "超期",
        ),
        (
            (InstrumentRecord.status == "超期")
            & (
                (InstrumentRecord.next_calibration_date >= today)
                | (InstrumentRecord.next_calibration_date.is_(None))
            ),
            "在用",
        ),
        else_=InstrumentRecord.status,
    ).label("effective_status")

    # 基础条件：未删除 + next_calibration_date 存在（用于到期统计）
    base = select(
        func.count().label("total"),
        func.sum(case((status_expr == "在用", 1), else_=0)).label("in_use"),
        func.sum(case((status_expr == "超期", 1), else_=0)).label("overdue"),
        func.sum(case((status_expr == "停用", 1), else_=0)).label("stopped"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date <= today),
                    1,
                ),
                else_=0,
            )
        ).label("due_today"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=7)),
                    1,
                ),
                else_=0,
            )
        ).label("due_7d"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=30)),
                    1,
                ),
                else_=0,
            )
        ).label("due_30d"),
        func.sum(
            case(
                (
                    InstrumentRecord.next_calibration_date.isnot(None)
                    & (InstrumentRecord.next_calibration_date >= today)
                    & (InstrumentRecord.next_calibration_date <= today + timedelta(days=90)),
                    1,
                ),
                else_=0,
            )
        ).label("due_90d"),
    ).where(
        InstrumentRecord.is_deleted == False,  # noqa: E712
    )

    result = await db.execute(base)
    row = result.one()
    return {
        "total": row.total or 0,
        "in_use": row.in_use or 0,
        "overdue": row.overdue or 0,
        "stopped": row.stopped or 0,
        "due_today": row.due_today or 0,
        "due_7d": row.due_7d or 0,
        "due_30d": row.due_30d or 0,
        "due_90d": row.due_90d or 0,
    }


async def get_gas_detector_overview(db: AsyncSession) -> dict[str, int]:
    """有毒有害可燃探测器总览统计。"""
    from sqlalchemy import case

    today = time_today()

    # 子查询计算每条记录的有效状态
    status_expr = case(
        (
            GasDetectorRecord.status.in_(["超期", "在用"])
            & (GasDetectorRecord.next_calibration_date < today),
            "超期",
        ),
        (
            (GasDetectorRecord.status == "超期")
            & (
                (GasDetectorRecord.next_calibration_date >= today)
                | (GasDetectorRecord.next_calibration_date.is_(None))
            ),
            "在用",
        ),
        else_=GasDetectorRecord.status,
    ).label("effective_status")

    base = select(
        func.count().label("total"),
        func.sum(case((status_expr == "在用", 1), else_=0)).label("in_use"),
        func.sum(case((status_expr == "超期", 1), else_=0)).label("overdue"),
        func.sum(case((status_expr == "停用", 1), else_=0)).label("stopped"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date <= today),
                    1,
                ),
                else_=0,
            )
        ).label("due_today"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=7)),
                    1,
                ),
                else_=0,
            )
        ).label("due_7d"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=30)),
                    1,
                ),
                else_=0,
            )
        ).label("due_30d"),
        func.sum(
            case(
                (
                    GasDetectorRecord.next_calibration_date.isnot(None)
                    & (GasDetectorRecord.next_calibration_date >= today)
                    & (GasDetectorRecord.next_calibration_date <= today + timedelta(days=90)),
                    1,
                ),
                else_=0,
            )
        ).label("due_90d"),
    ).where(
        GasDetectorRecord.is_deleted == False,  # noqa: E712
    )

    result = await db.execute(base)
    row = result.one()
    return {
        "total": row.total or 0,
        "in_use": row.in_use or 0,
        "overdue": row.overdue or 0,
        "stopped": row.stopped or 0,
        "due_today": row.due_today or 0,
        "due_7d": row.due_7d or 0,
        "due_30d": row.due_30d or 0,
        "due_90d": row.due_90d or 0,
    }


# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════
