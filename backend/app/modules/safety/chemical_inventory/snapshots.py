"""危化品库存快照落库/读取（每日日报与每周周报共用）。

快照按 snapshot_kind(daily/weekly) 区分：每日 19:30 落 daily 用于日报昨日环比，
每周五 15:30 落 weekly 用于周报周环比；同类同日期幂等（先软删后重插）。
"""
from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import ChemicalInventoryRecord, ChemicalInventorySnapshot

KIND_DAILY = "daily"
KIND_WEEKLY = "weekly"


async def take_snapshot(
    db: AsyncSession,
    snapshot_date: date,
    kind: str = KIND_WEEKLY,
    records: list[Any] | None = None,
    *,
    source: str | None = None,
) -> int:
    """把当前总表全量落一份快照（幂等：同类同日重复落则先软删）。

    records：直读编排注入的当前行（InventoryView/ORM duck-typing，字段名同名）；
    None（默认）时查 ORM 镜像——legacy 行为零变化。直读模式下镜像停更，
    daily/weekly 编排必须传 records，否则快照拍到的是停更前的旧数据。
    source：快照数据源标记（D8 环比断点；sheet 编排传 "sheet"，legacy 不传=NULL）。

    快照粒度 = (部门, 存放部位, 物料)（uq_cisnap_key 同键）。sheet 源同一部位
    可有多行同物料（多储罐各一行，2026-10-15 艾默实测）——落库前按键合并：
    数量/总量求和、风险标记保守取 warn。legacy 固定行台账按此键唯一，合并无操作。
    """
    if records is None:
        rows = list((await db.scalars(
            select(ChemicalInventoryRecord).where(
                ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
            )
        )).all())
    else:
        rows = list(records)
    old = list((await db.scalars(
        select(ChemicalInventorySnapshot).where(
            ChemicalInventorySnapshot.snapshot_date == snapshot_date,
            ChemicalInventorySnapshot.snapshot_kind == kind,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
        )
    )).all())
    for s in old:
        s.is_deleted = True

    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for r in rows:
        key = (r.department, r.storage_location, r.material_name)
        acc = merged.get(key)
        if acc is None:
            acc = merged[key] = {
                "row": r,
                "quantity": getattr(r, "quantity", None),
                "total_quantity_t": getattr(r, "total_quantity_t", None),
                "risk_flag": getattr(r, "risk_flag", "normal"),
            }
            continue
        for field in ("quantity", "total_quantity_t"):
            value = getattr(r, field, None)
            if value is not None:
                acc[field] = (acc[field] or 0) + value
        if getattr(r, "risk_flag", "normal") == "warn":
            acc["risk_flag"] = "warn"
    for acc in merged.values():
        r = acc["row"]
        db.add(ChemicalInventorySnapshot(
            snapshot_date=snapshot_date,
            snapshot_kind=kind,
            department=r.department,
            storage_location=r.storage_location,
            material_name=r.material_name,
            quantity=acc["quantity"],
            unit=r.unit,
            total_quantity_t=acc["total_quantity_t"],
            risk_flag=acc["risk_flag"],
            source=source,
        ))
    await db.flush()
    return len(merged)


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


async def load_prev_daily_snapshot_with_source(
    db: AsyncSession, today: date
) -> tuple[list[ChemicalInventorySnapshot], str | None]:
    """昨日 daily 快照行 + 其数据源标记（D8 环比断点判定用）。"""
    rows = await load_prev_daily_snapshot(db, today)
    return rows, snapshot_rows_source(rows)


def snapshot_rows_source(rows: list[Any]) -> str | None:
    """快照行集的数据源标记（首个非空值；全空 = legacy/总表口径）。"""
    return next((r.source for r in rows if r.source), None)
