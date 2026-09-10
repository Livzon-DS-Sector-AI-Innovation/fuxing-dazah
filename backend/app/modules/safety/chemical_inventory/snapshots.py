"""危化品库存快照落库/读取（每日日报与每周周报共用）。

快照按 snapshot_kind(daily/weekly) 区分：每日 19:30 落 daily 用于日报昨日环比，
每周五 15:30 落 weekly 用于周报周环比；同类同日期幂等（先软删后重插）。
"""
from __future__ import annotations

from datetime import date
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import ChemicalInventoryRecord, ChemicalInventorySnapshot

KIND_DAILY = "daily"
KIND_WEEKLY = "weekly"


async def take_snapshot(
    db: AsyncSession, snapshot_date: date, kind: str = KIND_WEEKLY
) -> int:
    """把当前总表全量落一份快照（幂等：同类同日重复落则先软删）。"""
    rows = list((await db.scalars(
        select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
        )
    )).all())
    old = list((await db.scalars(
        select(ChemicalInventorySnapshot).where(
            ChemicalInventorySnapshot.snapshot_date == snapshot_date,
            ChemicalInventorySnapshot.snapshot_kind == kind,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
        )
    )).all())
    for s in old:
        s.is_deleted = True
    for r in rows:
        db.add(ChemicalInventorySnapshot(
            snapshot_date=snapshot_date,
            snapshot_kind=kind,
            department=r.department,
            storage_location=r.storage_location,
            material_name=r.material_name,
            quantity=r.quantity,
            unit=r.unit,
            total_quantity_t=r.total_quantity_t,
            risk_flag=r.risk_flag,
        ))
    await db.flush()
    return len(rows)


async def prev_snapshot_date(
    db: AsyncSession, before: date, kind: str = KIND_WEEKLY
) -> date | None:
    """before 之前最近一份同类型快照日期。"""
    return cast(date | None, await db.scalar(
        select(func.max(ChemicalInventorySnapshot.snapshot_date)).where(
            ChemicalInventorySnapshot.snapshot_date < before,
            ChemicalInventorySnapshot.snapshot_kind == kind,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
        )
    ))


async def snapshot_rows_for_date(
    db: AsyncSession, snapshot_date: date, kind: str = KIND_WEEKLY
) -> list[ChemicalInventorySnapshot]:
    """某日某类型快照的全量行。"""
    return list((await db.scalars(
        select(ChemicalInventorySnapshot).where(
            ChemicalInventorySnapshot.snapshot_date == snapshot_date,
            ChemicalInventorySnapshot.snapshot_kind == kind,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
        )
    )).all())


async def load_prev_daily_snapshot(db: AsyncSession, today: date) -> list[ChemicalInventorySnapshot]:
    """今日之前最近一份 daily 快照行（日报昨日对比用；无则空列表）。"""
    prev = await prev_snapshot_date(db, today, kind=KIND_DAILY)
    if prev is None:
        return []
    return await snapshot_rows_for_date(db, prev, kind=KIND_DAILY)
