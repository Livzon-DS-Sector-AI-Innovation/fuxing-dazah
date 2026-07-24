"""计划中枢数据查询。"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)

__all__ = [
    "get_demand",
    "get_demand_by_no",
    "list_demands",
    "get_plan_order",
    "get_plan_order_by_no",
    "get_plan_orders_by_ids",
    "list_plan_orders",
    "get_plan_item",
    "list_plan_items",
    "get_plan_items_by_ids",
    "get_max_item_no",
    "list_plan_items_schedule_view",
    "find_overlapping_items",
    "get_plan_allocations_by_item",
    "get_plan_allocations_by_batch",
    "get_demand_allocations",
    "get_demand_allocation_by_id",
    "get_demand_allocations_by_item",
    "get_demand_allocations_by_items",
    "get_batches_for_allocations",
    "get_batch_by_no",
]


# ── Demand ──


async def get_demand(db: AsyncSession, demand_id: uuid.UUID) -> Demand | None:
    stmt = select(Demand).where(Demand.id == demand_id, Demand.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_demand_by_no(db: AsyncSession, demand_no: str) -> Demand | None:
    stmt = select(Demand).where(
        Demand.demand_no == demand_no, Demand.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_demands(
    db: AsyncSession,
    status: str | None = None,
    priority: str | None = None,
    source_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Demand], int]:
    stmt = select(Demand).where(Demand.is_deleted == False)  # noqa: E712
    if status:
        stmt = stmt.where(Demand.status == status)
    if priority:
        stmt = stmt.where(Demand.priority == priority)
    if source_type:
        stmt = stmt.where(Demand.source_type == source_type)
    if date_from:
        stmt = stmt.where(Demand.demand_date >= date_from)
    if date_to:
        stmt = stmt.where(Demand.demand_date <= date_to)
    if keyword:
        stmt = stmt.where(
            Demand.demand_no.ilike(f"%{keyword}%")
            | Demand.product_name.ilike(f"%{keyword}%")
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(Demand.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.execute(stmt)).scalars()), total


# ── PlanOrder ──


async def get_plan_order(db: AsyncSession, order_id: uuid.UUID) -> PlanOrder | None:
    stmt = select(PlanOrder).where(
        PlanOrder.id == order_id, PlanOrder.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_plan_order_by_no(db: AsyncSession, order_no: str) -> PlanOrder | None:
    stmt = select(PlanOrder).where(
        PlanOrder.order_no == order_no, PlanOrder.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_plan_orders_by_ids(db: AsyncSession, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, PlanOrder]:
    """批量获取计划单，供 N+1 优化。"""
    if not order_ids:
        return {}
    stmt = select(PlanOrder).where(
        PlanOrder.id.in_(order_ids), PlanOrder.is_deleted == False  # noqa: E712
    )
    orders = list((await db.execute(stmt)).scalars())
    return {o.id: o for o in orders}


async def list_plan_orders(
    db: AsyncSession,
    status: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PlanOrder], int]:
    stmt = select(PlanOrder).where(PlanOrder.is_deleted == False)  # noqa: E712
    if status:
        stmt = stmt.where(PlanOrder.status == status)
    if priority:
        stmt = stmt.where(PlanOrder.priority == priority)
    if date_from:
        stmt = stmt.where(PlanOrder.scheduled_start >= date_from)
    if date_to:
        stmt = stmt.where(PlanOrder.scheduled_end <= date_to)
    if keyword:
        stmt = stmt.where(
            PlanOrder.order_no.ilike(f"%{keyword}%")
            | PlanOrder.title.ilike(f"%{keyword}%")
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(PlanOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.execute(stmt)).scalars()), total


# ── PlanItem ──


async def get_plan_item(db: AsyncSession, item_id: uuid.UUID) -> PlanItem | None:
    stmt = select(PlanItem).where(
        PlanItem.id == item_id, PlanItem.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_plan_items(db: AsyncSession, plan_order_id: uuid.UUID) -> list[PlanItem]:
    stmt = (
        select(PlanItem)
        .where(
            PlanItem.plan_order_id == plan_order_id,
            PlanItem.is_deleted == False,  # noqa: E712
        )
        .order_by(PlanItem.sort_order, PlanItem.item_no)
    )
    return list((await db.execute(stmt)).scalars())


async def get_plan_items_by_ids(db: AsyncSession, item_ids: list[uuid.UUID]) -> list[PlanItem]:
    if not item_ids:
        return []
    stmt = select(PlanItem).where(
        PlanItem.id.in_(item_ids), PlanItem.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_max_item_no(db: AsyncSession, plan_order_id: uuid.UUID) -> int:
    """获取某计划单当前最大明细行号。"""
    stmt = (
        select(func.coalesce(func.max(PlanItem.item_no), 0))
        .where(PlanItem.plan_order_id == plan_order_id, PlanItem.is_deleted == False)  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one()


# ── 排程视图查询 ──


async def list_plan_items_schedule_view(
    db: AsyncSession,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    equipment_id: str | None = None,
) -> list[PlanItem]:
    """获取排程视图的 PlanItem 列表，join PlanOrder 过滤已确认/已下达状态。"""
    stmt = (
        select(PlanItem)
        .join(PlanOrder, PlanItem.plan_order_id == PlanOrder.id)
        .where(
            PlanItem.is_deleted == False,  # noqa: E712
            PlanOrder.is_deleted == False,  # noqa: E712
            PlanOrder.status.in_(("confirmed", "released")),
            PlanItem.planned_start.isnot(None),
            PlanItem.planned_end.isnot(None),
        )
    )
    if from_time:
        stmt = stmt.where(PlanItem.planned_end >= from_time)
    if to_time:
        stmt = stmt.where(PlanItem.planned_start <= to_time)
    if equipment_id:
        stmt = stmt.where(PlanItem.equipment_id == equipment_id)
    return list((await db.execute(stmt)).scalars())


# ── 设备冲突检测 ──


async def find_overlapping_items(
    db: AsyncSession,
    equipment_id: str,
    planned_start: datetime,
    planned_end: datetime,
    exclude_item_id: uuid.UUID | None = None,
) -> list[PlanItem]:
    """查询同一设备上时间重叠的 PlanItem。"""
    stmt = select(PlanItem).where(
        PlanItem.is_deleted == False,  # noqa: E712
        PlanItem.equipment_id == equipment_id,
        PlanItem.planned_start.isnot(None),
        PlanItem.planned_end.isnot(None),
        PlanItem.planned_start < planned_end,
        PlanItem.planned_end > planned_start,
    )
    if exclude_item_id:
        stmt = stmt.where(PlanItem.id != exclude_item_id)
    return list((await db.execute(stmt)).scalars())


# ── Allocation ──


async def get_plan_allocations_by_item(db: AsyncSession, plan_item_id: uuid.UUID) -> list[PlanAllocation]:
    stmt = select(PlanAllocation).where(
        PlanAllocation.plan_item_id == plan_item_id,
        PlanAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_plan_allocations_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[PlanAllocation]:
    stmt = select(PlanAllocation).where(
        PlanAllocation.batch_id == batch_id,
        PlanAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


# ── DemandAllocation ──


async def get_demand_allocations(db: AsyncSession, demand_id: uuid.UUID) -> list[DemandAllocation]:
    stmt = select(DemandAllocation).where(
        DemandAllocation.demand_id == demand_id,
        DemandAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_demand_allocation_by_id(db: AsyncSession, alloc_id: uuid.UUID) -> DemandAllocation | None:
    stmt = select(DemandAllocation).where(
        DemandAllocation.id == alloc_id, DemandAllocation.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_demand_allocations_by_item(db: AsyncSession, plan_item_id: uuid.UUID) -> list[DemandAllocation]:
    stmt = select(DemandAllocation).where(
        DemandAllocation.plan_item_id == plan_item_id,
        DemandAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_demand_allocations_by_items(
    db: AsyncSession, item_ids: list[uuid.UUID],
) -> list[DemandAllocation]:
    """批量获取需求分配，供 N+1 优化。"""
    if not item_ids:
        return []
    stmt = select(DemandAllocation).where(
        DemandAllocation.plan_item_id.in_(item_ids),
        DemandAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


# ── Batch 补充查询 ──


async def get_batches_for_allocations(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Batch]:
    """批量获取批次号/状态，供 Allocation 填充。"""
    if not batch_ids:
        return {}
    stmt = select(Batch).where(
        Batch.id.in_(batch_ids), Batch.is_deleted == False  # noqa: E712
    )
    batches = list((await db.execute(stmt)).scalars())
    return {b.id: b for b in batches}


async def get_batch_by_no(db: AsyncSession, batch_no: str) -> Batch | None:
    """按批号查批次，用于冲突检测。"""
    stmt = select(Batch).where(
        Batch.batch_no == batch_no, Batch.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()
