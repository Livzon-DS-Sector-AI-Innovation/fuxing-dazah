"""检定到期查询与飞书通知部门查询。"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as time_today
from app.modules.meter.models import Department, GasDetectorRecord, InstrumentRecord


async def list_instruments_due_for_calibration(
    db: AsyncSession, *, days_before: int = 30
) -> list[InstrumentRecord]:
    """查询需检定的标准计量器具。

    days_before = 0  → 截止今天（含所有已过期 + 今天到期）
    days_before > 0  → 未来 N 天内到期
    """
    today = time_today()
    deadline = today + timedelta(days=days_before)
    stmt = select(InstrumentRecord).where(
        InstrumentRecord.is_deleted == False,  # noqa: E712
        InstrumentRecord.next_calibration_date.isnot(None),
        InstrumentRecord.next_calibration_date <= deadline,
    )
    if days_before > 0:
        # 未来 N 天：加下界
        stmt = stmt.where(InstrumentRecord.next_calibration_date >= today)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════
# 有毒有害可燃探测器
# ═══════════════════════════════════════════


async def list_gas_detectors_due_for_calibration(
    db: AsyncSession, *, days_before: int = 30
) -> list[GasDetectorRecord]:
    """查询需检定的有毒有害可燃探测器。

    days_before = 0  → 截止今天（含所有已过期 + 今天到期）
    days_before > 0  → 未来 N 天内到期
    """
    today = time_today()
    deadline = today + timedelta(days=days_before)
    stmt = select(GasDetectorRecord).where(
        GasDetectorRecord.is_deleted == False,  # noqa: E712
        GasDetectorRecord.next_calibration_date.isnot(None),
        GasDetectorRecord.next_calibration_date <= deadline,
    )
    if days_before > 0:
        # 未来 N 天：加下界
        stmt = stmt.where(GasDetectorRecord.next_calibration_date >= today)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_instruments_due_grouped(
    db: AsyncSession, department: str,
) -> dict[str, list[InstrumentRecord]]:
    """按 4 个时间窗口分组查询指定部门的标准器具到期记录。

    分组 key: "due_today"（截止今天, 含超期）, "due_7d"（未来 1-7 天）,
             "due_30d"（未来 8-30 天）, "due_90d"（未来 31-90 天）
    """
    today = time_today()
    ranges: list[tuple[str, date | None, date]] = [
        ("due_today", None, today),                                         # 截止今天（含超期）
        ("due_7d", today + timedelta(days=1), today + timedelta(days=7)),   # 1-7 天
        ("due_30d", today + timedelta(days=8), today + timedelta(days=30)), # 8-30 天
        ("due_90d", today + timedelta(days=31), today + timedelta(days=90)),# 31-90 天
    ]

    grouped: dict[str, list[InstrumentRecord]] = {}
    for key, start, end in ranges:
        stmt = select(InstrumentRecord).where(
            InstrumentRecord.is_deleted == False,  # noqa: E712
            InstrumentRecord.department == department,
            InstrumentRecord.next_calibration_date.isnot(None),
            InstrumentRecord.next_calibration_date <= end,
        )
        if start is not None:
            stmt = stmt.where(InstrumentRecord.next_calibration_date >= start)
        result = await db.execute(stmt)
        grouped[key] = list(result.scalars().all())

    return grouped


async def list_gas_detectors_due_grouped(
    db: AsyncSession, department: str,
) -> dict[str, list[GasDetectorRecord]]:
    """按 4 个时间窗口分组查询指定部门的探测器到期记录。

    分组 key: "due_today"（截止今天, 含超期）, "due_7d"（未来 1-7 天）,
             "due_30d"（未来 8-30 天）, "due_90d"（未来 31-90 天）
    """
    today = time_today()
    ranges: list[tuple[str, date | None, date]] = [
        ("due_today", None, today),                                         # 截止今天（含超期）
        ("due_7d", today + timedelta(days=1), today + timedelta(days=7)),   # 1-7 天
        ("due_30d", today + timedelta(days=8), today + timedelta(days=30)), # 8-30 天
        ("due_90d", today + timedelta(days=31), today + timedelta(days=90)),# 31-90 天
    ]

    grouped: dict[str, list[GasDetectorRecord]] = {}
    for key, start, end in ranges:
        stmt = select(GasDetectorRecord).where(
            GasDetectorRecord.is_deleted == False,  # noqa: E712
            GasDetectorRecord.department == department,
            GasDetectorRecord.next_calibration_date.isnot(None),
            GasDetectorRecord.next_calibration_date <= end,
        )
        if start is not None:
            stmt = stmt.where(GasDetectorRecord.next_calibration_date >= start)
        result = await db.execute(stmt)
        grouped[key] = list(result.scalars().all())

    return grouped


async def get_notifiable_departments(db: AsyncSession) -> list[Department]:
    """查询所有开启自动提醒且有负责人的部门。"""
    stmt = select(Department).where(
        Department.is_deleted == False,  # noqa: E712
        Department.auto_notify_enabled == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    # 在 Python 侧过滤：heads 非空
    depts = result.scalars().all()
    return [d for d in depts if d.heads and len(d.heads) > 0]
