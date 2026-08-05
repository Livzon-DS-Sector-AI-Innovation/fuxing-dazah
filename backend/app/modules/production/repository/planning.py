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
    PlanChangeLog,
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
    "get_plan_allocations_by_batches",
    "get_demand_allocations",
    "get_demand_allocation_by_id",
    "get_demand_allocations_by_item",
    "get_demand_allocations_by_items",
    "get_batches_for_allocations",
    "get_batch_by_no",
    "get_plan_item_by_batch_no",
    "get_parent_batch_id",
    "get_child_batch_ids",
    "get_chain_node_execution_progress",
    "get_change_logs",
    "get_batches_by_plan_items",
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
        .order_by(PlanItem.planned_start.asc().nulls_last(), PlanItem.sort_order, PlanItem.item_no)
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
            PlanOrder.status.in_(("draft", "confirmed", "released", "completed")),
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


async def get_plan_allocations_by_batches(
    db: AsyncSession, batch_ids: list[uuid.UUID],
) -> list[PlanAllocation]:
    """批量反向查询：batch → plan_item，供工作台计划批次可见性。ponytail: .in_ 版本。"""
    if not batch_ids:
        return []
    stmt = select(PlanAllocation).where(
        PlanAllocation.batch_id.in_(batch_ids),
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


async def get_plan_item_by_batch_no(
    db: AsyncSession, batch_no: str, exclude_item_id: uuid.UUID | None = None,
) -> PlanItem | None:
    """按批号查计划项，用于创建/编辑时的唯一性校验。"""
    stmt = (
        select(PlanItem)
        .where(
            PlanItem.batch_no == batch_no,
            PlanItem.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    if exclude_item_id:
        stmt = stmt.where(PlanItem.id != exclude_item_id)
    return (await db.execute(stmt)).scalars().first()


# ── 批次追溯 / 执行进度 / 变更日志 ──


async def get_parent_batch_id(
    db: AsyncSession, child_id: uuid.UUID,
) -> uuid.UUID | None:
    """按子批次查父批次（谱系回溯）。单线假设下父唯一，取第一条。"""
    from app.modules.production.models.batch import BatchLink

    stmt = (
        select(BatchLink.parent_batch_id)
        .where(
            BatchLink.child_batch_id == child_id,
            BatchLink.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_child_batch_ids(
    db: AsyncSession, parent_id: uuid.UUID,
) -> list[uuid.UUID]:
    """按父批次查全部非删除子批次 id。"""
    from app.modules.production.models.batch import BatchLink

    stmt = (
        select(BatchLink.child_batch_id)
        .where(
            BatchLink.parent_batch_id == parent_id,
            BatchLink.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )
    return list((await db.execute(stmt)).scalars())


async def get_chain_node_execution_progress(
    db: AsyncSession, batch_ids: list[uuid.UUID],
) -> tuple[str | None, str | None]:
    """返回 (latest_node_name, latest_node_status)：谱系链上所有批次合并后最远执行到的工序。

    拆分后子批次继承父批次已完成的工序进度，前端进度条按整条链计算。
    """
    if not batch_ids:
        return None, None
    from app.modules.production.models.execution import NodeExecution
    from app.modules.production.models.route import RouteNode

    stmt = (
        select(RouteNode.name, NodeExecution.status)
        .join(NodeExecution, NodeExecution.node_id == RouteNode.id)
        .where(
            NodeExecution.batch_id.in_(batch_ids),
            NodeExecution.is_deleted == False,  # noqa: E712
            RouteNode.is_deleted == False,  # noqa: E712
        )
        # 同一节点多次执行（返工 seq+1）时取最新一次，避免状态随机
        .order_by(RouteNode.sort_order.desc(), NodeExecution.execution_seq.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None, None
    return row[0], row[1]


async def get_change_logs(db: AsyncSession, plan_order_id: uuid.UUID) -> list[PlanChangeLog]:
    """获取计划单变更日志，按版本倒序。"""
    stmt = (
        select(PlanChangeLog)
        .where(
            PlanChangeLog.plan_order_id == plan_order_id,
            PlanChangeLog.is_deleted == False,  # noqa: E712
        )
        .order_by(PlanChangeLog.plan_version.desc())
    )
    return list((await db.execute(stmt)).scalars())


async def get_batches_by_plan_items(
    db: AsyncSession, item_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Batch]:
    """PlanItem → Batch 批量映射。"""
    if not item_ids:
        return {}
    stmt = (
        select(PlanAllocation.plan_item_id, Batch)
        .join(Batch, Batch.id == PlanAllocation.batch_id)
        .where(
            PlanAllocation.plan_item_id.in_(item_ids),
            PlanAllocation.is_deleted == False,  # noqa: E712
            Batch.is_deleted == False,  # noqa: E712
        )
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: row[1] for row in rows}
