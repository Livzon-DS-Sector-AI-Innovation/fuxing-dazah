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
    "list_released_plan_batches_by_route",
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
    "list_plan_item_nos",
    "list_batch_nos",
    "get_parent_batch_id",
    "get_child_batch_ids",
    "get_chain_node_execution_progress",
    "get_change_logs",
    "get_batches_by_plan_items",
    "get_chain_batches_by_plan_items",
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


async def list_released_plan_batches_by_route(
    db: AsyncSession, route_id: uuid.UUID
) -> list[tuple[Batch, PlanItem, str, int]]:
    """工序看板计划批次：路线下"已分配未执行"的实际批次与其计划来源。

    经 PlanAllocation → Batch 取实际创建的批次（批号以 Batch.batch_no 为准，
    下达时可能经 _ensure_unique_batch_no 去重改写），过滤条件：
    - 计划单已下达（released）
    - 计划项已分配且未开工（item.status == 'allocated'）
    - 计划项匹配该路线

    返回 (批次, 计划项, 计划单号, 计划版本)，按计划开始时间升序（nulls last）再行号排序。
    """
    stmt = (
        select(Batch, PlanItem, PlanOrder.order_no, PlanOrder.plan_version)
        .join(PlanAllocation, PlanAllocation.batch_id == Batch.id)
        .join(PlanItem, PlanItem.id == PlanAllocation.plan_item_id)
        .join(PlanOrder, PlanOrder.id == PlanItem.plan_order_id)
        .where(
            PlanItem.route_id == route_id,
            PlanItem.status == "allocated",
            Batch.is_deleted == False,  # noqa: E712
            PlanItem.is_deleted == False,  # noqa: E712
            PlanOrder.status == "released",
            PlanOrder.is_deleted == False,  # noqa: E712
        )
        .order_by(
            PlanItem.planned_start.asc().nulls_last(),
            PlanItem.item_no,
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


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


async def list_plan_item_nos(db: AsyncSession, batch_nos: list[str]) -> set[str]:
    """批量查计划项占用的批号（软删除项不计）。"""
    if not batch_nos:
        return set()
    stmt = select(PlanItem.batch_no).where(
        PlanItem.batch_no.in_(batch_nos),
        PlanItem.is_deleted == False,  # noqa: E712
    )
    # batch_no 列为可空，IN 匹配到的均为非空值；过滤 None 满足 mypy 类型收窄
    return {no for no in (await db.execute(stmt)).scalars() if no is not None}


async def list_batch_nos(db: AsyncSession, batch_nos: list[str]) -> set[str]:
    """批量查真实批次占用的批号（软删除批次不计）。"""
    if not batch_nos:
        return set()
    stmt = select(Batch.batch_no).where(
        Batch.batch_no.in_(batch_nos),
        Batch.is_deleted == False,  # noqa: E712
    )
    return set((await db.execute(stmt)).scalars())


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


async def get_chain_batches_by_plan_items(
    db: AsyncSession, item_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[Batch]]:
    """PlanItem → 谱系链上全部批次（根 + 跨边界子批次），批量版。

    与 planning_service._collect_chain_batches 同规则：根批次取自
    PlanAllocation，沿 BatchLink 逐层下钻；cancelled 批次不计入，
    仅在**同层全部报废**时继续下钻其子批次（报废不打断链）；一旦
    同层存在有效子批次，报废分支即为废弃分支，不再下钻。
    与之的差异仅在多有效子批次时取全部分支（统计场景需要），
    _collect_chain_batches 为单线取第一个。
    """
    if not item_ids:
        return {}
    from app.modules.production.models.batch import BatchLink

    rows = (
        await db.execute(
            select(PlanAllocation.plan_item_id, Batch)
            .join(Batch, Batch.id == PlanAllocation.batch_id)
            .where(
                PlanAllocation.plan_item_id.in_(item_ids),
                PlanAllocation.is_deleted == False,  # noqa: E712
                Batch.is_deleted == False,  # noqa: E712
            )
        )
    ).all()
    result: dict[uuid.UUID, list[Batch]] = {}
    # 已到访批次 → 所属计划项；兼作环/合流防护（首个归属者优先）
    owner_by_batch: dict[uuid.UUID, uuid.UUID] = {}
    frontier: list[Batch] = []
    for item_id, batch in rows:
        owner_by_batch[batch.id] = item_id
        frontier.append(batch)
        if batch.status != "cancelled":
            result.setdefault(item_id, []).append(batch)
    while frontier:
        parents = [b.id for b in frontier]
        child_rows = (
            await db.execute(
                select(BatchLink.parent_batch_id, Batch)
                .join(Batch, Batch.id == BatchLink.child_batch_id)
                .where(
                    BatchLink.parent_batch_id.in_(parents),
                    BatchLink.is_deleted == False,  # noqa: E712
                    Batch.is_deleted == False,  # noqa: E712
                )
            )
        ).all()
        children_by_parent: dict[uuid.UUID, list[Batch]] = {}
        for parent_id, child in child_rows:
            children_by_parent.setdefault(parent_id, []).append(child)
        frontier = []
        for parent_id, children in children_by_parent.items():
            item_id = owner_by_batch.get(parent_id)
            if item_id is None:
                continue
            # 同层有有效子批次时只走有效分支，报废分支视为废弃不再下钻
            valid = [c for c in children if c.status != "cancelled"]
            for child in valid or children:
                if child.id in owner_by_batch:
                    continue
                owner_by_batch[child.id] = item_id
                frontier.append(child)
                if child.status != "cancelled":
                    result.setdefault(item_id, []).append(child)
    return result
