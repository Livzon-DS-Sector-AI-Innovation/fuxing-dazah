"""计划中枢业务逻辑：需求、计划单、计划项、分配、下达、追溯。"""

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import Batch
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)
from app.modules.production.schemas.planning import (
    DemandAllocationCreate,
    DemandAllocationOut,
    DemandCreate,
    DemandDetailOut,
    DemandUpdate,
    PlanAllocationOut,
    PlanItemCreate,
    PlanItemOut,
    PlanItemScheduleIn,
    PlanItemUpdate,
    PlanOrderCreate,
    PlanOrderDetailOut,
    PlanOrderUpdate,
    ScheduleViewItem,
    TraceNode,
)
from app.platform.identity.models import User

# ═══════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════

def _generate_demand_no() -> str:
    """生成需求编号 DM-YYYYMMDD-NNNN。ponytail: 简单时间戳简化为日期+计数器。"""
    import random

    today = date.today().strftime("%Y%m%d")
    suffix = random.randint(0, 9999)
    return f"DM-{today}-{suffix:04d}"


def _generate_order_no() -> str:
    """生成计划单号 PO-YYYYMMDD-NNNN。"""
    import random

    today = date.today().strftime("%Y%m%d")
    suffix = random.randint(0, 9999)
    return f"PO-{today}-{suffix:04d}"


# ponytail: 校验时间范围基本合法性，不检测实际重叠
def _check_time_range_valid(planned_start: datetime, planned_end: datetime) -> bool:
    return planned_start < planned_end


async def _ensure_unique_batch_no(db: AsyncSession, base_no: str) -> str:
    """生成唯一批号，若冲突则追加后缀 -N。"""
    candidate = base_no
    n = 1
    while await repo.get_batch_by_no(db, candidate):
        n += 1
        candidate = f"{base_no}-{n}"
    return candidate


# ═══════════════════════════════════════════
# Demand
# ═══════════════════════════════════════════

def _recalc_demand_fulfillment(demand: Demand, allocations: list[DemandAllocation]) -> None:
    """根据关联的 DemandAllocation 重算 allocated_quantity，根据已兑现批次重算 fulfilled_quantity。"""
    demand.allocated_quantity = sum(a.allocated_quantity for a in allocations)
    # fulfilled 需要 plan_allocations 层级的溯源（本次暂在 trace 链路中计算）


def _update_demand_status(demand: Demand) -> None:
    """根据履约量更新需求状态。"""
    if demand.fulfilled_quantity >= demand.demanded_quantity:
        demand.status = "fulfilled"
    elif demand.allocated_quantity > 0:
        demand.status = "partial"
    else:
        demand.status = "confirmed"


async def create_demand(
    db: AsyncSession, payload: DemandCreate, user: User | None,
) -> Demand:
    if not payload.demand_no:
        payload.demand_no = _generate_demand_no()
    if await repo.get_demand_by_no(db, payload.demand_no):
        raise DuplicateException("需求编号", payload.demand_no)
    demand = Demand(
        demand_no=payload.demand_no,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        product_id=payload.product_id,
        product_name=payload.product_name,
        demanded_quantity=payload.demanded_quantity,
        unit=payload.unit,
        demand_date=payload.demand_date,
        priority=payload.priority,
        customer_name=payload.customer_name,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(demand)
    await db.flush()
    return demand


async def update_demand(
    db: AsyncSession, demand_id: uuid.UUID, payload: DemandUpdate, user: User | None,
) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status not in ("pending", "confirmed"):
        raise AppException(status_code=400, message="仅 pending/confirmed 状态的需求可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(demand, field, value)
    demand.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_demand(db, demand_id)
    assert refreshed is not None
    return refreshed


async def confirm_demand(db: AsyncSession, demand_id: uuid.UUID, user: User | None) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status != "pending":
        raise AppException(status_code=400, message="仅 pending 状态的需求可确认")
    demand.status = "confirmed"
    demand.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_demand(db, demand_id)
    assert refreshed is not None
    return refreshed


async def cancel_demand(db: AsyncSession, demand_id: uuid.UUID, user: User | None) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status in ("closed", "cancelled"):
        raise AppException(status_code=400, message="已关闭/已取消的需求不能取消")
    demand.status = "cancelled"
    demand.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_demand(db, demand_id)
    assert refreshed is not None
    return refreshed


async def delete_demand(db: AsyncSession, demand_id: uuid.UUID, user: User | None) -> None:
    """软删除需求，不做状态限制。"""
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    demand.is_deleted = True
    demand.updated_by = user.id if user else None
    await db.flush()


async def get_demand_detail(db: AsyncSession, demand_id: uuid.UUID) -> DemandDetailOut:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    da_list = await repo.get_demand_allocations(db, demand_id)
    # 批量获取 plan_items 和 plan_orders（N+1 优化）
    item_ids = list({da.plan_item_id for da in da_list})
    items_map = {i.id: i for i in await repo.get_plan_items_by_ids(db, item_ids)} if item_ids else {}
    order_ids = list({i.plan_order_id for i in items_map.values()})
    orders_map = await repo.get_plan_orders_by_ids(db, order_ids) if order_ids else {}
    das = []
    for da in da_list:
        dao = DemandAllocationOut.model_validate(da)
        dao.demand_no = demand.demand_no
        item = items_map.get(da.plan_item_id)
        if item:
            dao.item_no = item.item_no
            dao.intermediate_type_name = item.intermediate_type_name
            order = orders_map.get(item.plan_order_id)
            if order:
                dao.plan_order_no = order.order_no
        das.append(dao)
    detail = DemandDetailOut.model_validate(demand)
    detail.allocations = das
    return detail


async def list_demands_paged(
    db: AsyncSession,
    status: str | None,
    priority: str | None,
    source_type: str | None,
    date_from: date | None,
    date_to: date | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Demand], int]:
    return await repo.list_demands(
        db, status, priority, source_type, date_from, date_to, keyword, page, page_size,
    )


# ═══════════════════════════════════════════
# PlanOrder
# ═══════════════════════════════════════════

async def create_plan_order(
    db: AsyncSession, payload: PlanOrderCreate, user: User | None,
) -> PlanOrder:
    if not payload.order_no:
        payload.order_no = _generate_order_no()
    if await repo.get_plan_order_by_no(db, payload.order_no):
        raise DuplicateException("计划单号", payload.order_no)
    order = PlanOrder(
        order_no=payload.order_no,
        title=payload.title,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        priority=payload.priority,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(order)
    await db.flush()
    return order


async def update_plan_order(
    db: AsyncSession, order_id: uuid.UUID, payload: PlanOrderUpdate, user: User | None,
) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(order, field, value)
    order.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def confirm_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可确认")
    items = await repo.list_plan_items(db, order_id)
    if not items:
        raise AppException(status_code=400, message="计划单无计划项，无法确认")
    order.status = "confirmed"
    order.plan_version += 1
    order.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def release_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    """下达：所有 PlanItem 生成 Batch + Allocation。"""
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "confirmed":
        raise AppException(status_code=400, message="仅 confirmed 状态的计划单可下达")
    items = await repo.list_plan_items(db, order_id)
    unscheduled = [i for i in items if i.status != "scheduled"]
    if unscheduled:
        raise AppException(
            status_code=400,
            message=f"以下计划项未排程: {[i.item_no for i in unscheduled]}",
        )
    # 事务内：为每个 PlanItem 创建 Batch + Allocation
    for item in items:
        if not item.route_id:
            raise AppException(
                status_code=400,
                message=f"计划项 {item.item_no} 未指定工艺路线，无法生成批次",
            )
        batch_no = await _ensure_unique_batch_no(db, f"{order.order_no}-{item.item_no}")
        batch = Batch(
            batch_no=batch_no,  # ponytail: 自动生成唯一批号
            product_id=item.intermediate_type_id,
            route_id=item.route_id,
            status="scheduled",
            quantity=item.planned_quantity,
            unit=item.unit,
            creation_type="plan",
            plan_version=order.plan_version,
            created_by=user.id if user else None,
        )
        db.add(batch)
        await db.flush()
        alloc = PlanAllocation(
            plan_item_id=item.id,
            batch_id=batch.id,
            allocated_quantity=item.planned_quantity,
            created_by=user.id if user else None,
        )
        db.add(alloc)
        item.status = "allocated"
        item.updated_by = user.id if user else None
    order.status = "released"
    order.plan_version += 1
    order.updated_by = user.id if user else None
    await db.flush()
    # 更新 Demand 履约量（批量查询优化）
    if items:
        item_ids = [i.id for i in items]
        all_das = await repo.get_demand_allocations_by_items(db, item_ids)
        demand_ids = {da.demand_id for da in all_das}
        for did in demand_ids:
            demand = await repo.get_demand(db, did)
            if demand:
                das_for_demand = [da for da in all_das if da.demand_id == did]
                _recalc_demand_fulfillment(demand, das_for_demand)
                _update_demand_status(demand)
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def close_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status not in ("released", "completed"):
        raise AppException(status_code=400, message="仅 released/completed 状态的计划单可关闭")
    order.status = "closed"
    order.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def delete_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> None:
    """软删除计划单，不做状态限制。"""
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    order.is_deleted = True
    order.updated_by = user.id if user else None
    await db.flush()


async def get_plan_order_detail(db: AsyncSession, order_id: uuid.UUID) -> PlanOrderDetailOut:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    items = await repo.list_plan_items(db, order_id)
    item_outs: list[PlanItemOut] = []
    for item in items:
        pio = PlanItemOut.model_validate(item)
        # 填充 allocations
        plan_allocs = await repo.get_plan_allocations_by_item(db, item.id)
        pio.allocations = []
        if plan_allocs:
            batch_ids = [a.batch_id for a in plan_allocs]
            batch_map = await repo.get_batches_for_allocations(db, batch_ids)
            for pa in plan_allocs:
                pao = PlanAllocationOut.model_validate(pa)
                b = batch_map.get(pa.batch_id)
                if b:
                    pao.batch_no = b.batch_no
                    pao.batch_status = b.status
                pio.allocations.append(pao)
        # 填充 demand_allocations
        da_list = await repo.get_demand_allocations_by_item(db, item.id)
        pio.demand_allocations = []
        for da in da_list:
            dao = DemandAllocationOut.model_validate(da)
            demand = await repo.get_demand(db, da.demand_id)
            if demand:
                dao.demand_no = demand.demand_no
            dao.plan_order_no = order.order_no
            dao.item_no = item.item_no
            dao.intermediate_type_name = item.intermediate_type_name
            pio.demand_allocations.append(dao)
        item_outs.append(pio)
    detail = PlanOrderDetailOut.model_validate(order)
    detail.items = item_outs
    return detail


async def list_plan_orders_paged(
    db: AsyncSession,
    status: str | None,
    priority: str | None,
    date_from: date | None,
    date_to: date | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[PlanOrder], int]:
    return await repo.list_plan_orders(
        db, status, priority, date_from, date_to, keyword, page, page_size,
    )


# ═══════════════════════════════════════════
# PlanItem
# ═══════════════════════════════════════════

async def create_plan_item(
    db: AsyncSession, order_id: uuid.UUID, payload: PlanItemCreate, user: User | None,
) -> PlanItem:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可添加计划项")
    max_no = await repo.get_max_item_no(db, order_id)
    item_no = max_no + 1
    item = PlanItem(
        plan_order_id=order_id,
        item_no=item_no,
        intermediate_type_id=payload.intermediate_type_id,
        intermediate_type_name=payload.intermediate_type_name,
        route_id=payload.route_id,
        equipment_id=payload.equipment_id,
        planned_quantity=payload.planned_quantity,
        unit=payload.unit,
        priority=payload.priority,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(item)
    await db.flush()
    return item


async def update_plan_item(
    db: AsyncSession, item_id: uuid.UUID, payload: PlanItemUpdate, user: User | None,
) -> PlanItem:
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status not in ("draft", "scheduled"):
        raise AppException(status_code=400, message="仅 draft/scheduled 状态的计划项可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    item.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_item(db, item_id)
    assert refreshed is not None
    return refreshed


async def delete_plan_item(db: AsyncSession, item_id: uuid.UUID, user: User | None) -> None:
    """软删除计划项，不做状态限制。"""
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    item.is_deleted = True
    item.updated_by = user.id if user else None
    await db.flush()


async def schedule_plan_item(
    db: AsyncSession, item_id: uuid.UUID, payload: PlanItemScheduleIn, user: User | None,
) -> tuple[PlanItem, list[dict]]:
    """排程操作：设置计划项的时间和设备。返回 (PlanItem, 冲突列表)。"""
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status not in ("draft", "scheduled"):
        raise AppException(status_code=400, message="仅 draft/scheduled 状态的计划项可排程")
    if payload.planned_start is not None:
        item.planned_start = payload.planned_start
    if payload.planned_end is not None:
        item.planned_end = payload.planned_end
    if payload.equipment_id is not None:
        item.equipment_id = payload.equipment_id
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    warnings: list[dict] = []
    if item.planned_start and item.planned_end:
        if not _check_time_range_valid(item.planned_start, item.planned_end):
            raise AppException(status_code=400, message="计划开始时间必须早于结束时间")
        # 设备冲突检测（告警但不阻断）
        if item.equipment_id:
            conflicts = await repo.find_overlapping_items(
                db, item.equipment_id, item.planned_start, item.planned_end, item.id,
            )
            for c in conflicts:
                warnings.append({
                    "item_id": str(c.id),
                    "item_no": c.item_no,
                    "intermediate_type_name": c.intermediate_type_name,
                    "planned_start": c.planned_start.isoformat() if c.planned_start else None,
                    "planned_end": c.planned_end.isoformat() if c.planned_end else None,
                })
        item.status = "scheduled"
    item.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_item(db, item_id)
    assert refreshed is not None
    return refreshed, warnings


async def allocate_plan_item(
    db: AsyncSession, item_id: uuid.UUID, user: User | None,
) -> PlanItem:
    """单独分配计划项生成 Batch。"""
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status != "scheduled":
        raise AppException(status_code=400, message="仅 scheduled 状态的计划项可分配")
    if not item.route_id:
        raise AppException(
            status_code=400,
            message=f"计划项 {item.item_no} 未指定工艺路线，无法生成批次",
        )
    order = await repo.get_plan_order(db, item.plan_order_id)
    if not order:
        raise NotFoundException("计划单", str(item.plan_order_id))
    batch_no = await _ensure_unique_batch_no(db, f"{order.order_no}-{item.item_no}")
    batch = Batch(
        batch_no=batch_no,
        product_id=item.intermediate_type_id,
        route_id=item.route_id,
        status="scheduled",
        quantity=item.planned_quantity,
        unit=item.unit,
        creation_type="plan",
        plan_version=order.plan_version,
        created_by=user.id if user else None,
    )
    db.add(batch)
    await db.flush()
    alloc = PlanAllocation(
        plan_item_id=item.id,
        batch_id=batch.id,
        allocated_quantity=item.planned_quantity,
        created_by=user.id if user else None,
    )
    db.add(alloc)
    item.status = "allocated"
    item.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_item(db, item_id)
    assert refreshed is not None
    return refreshed


# ═══════════════════════════════════════════
# 排程视图
# ═══════════════════════════════════════════

async def get_schedule_view(
    db: AsyncSession,
    from_time: datetime | None,
    to_time: datetime | None,
    equipment_id: str | None,
) -> list[ScheduleViewItem]:
    items = await repo.list_plan_items_schedule_view(db, from_time, to_time, equipment_id)
    # 批量获取 plan_orders（N+1 优化）
    order_ids = list({i.plan_order_id for i in items})
    orders_map = await repo.get_plan_orders_by_ids(db, order_ids)
    result: list[ScheduleViewItem] = []
    for item in items:
        order = orders_map.get(item.plan_order_id)
        if not order:
            continue
        result.append(ScheduleViewItem(
            plan_order_id=order.id,
            order_no=order.order_no,
            order_title=order.title,
            order_status=order.status,
            order_priority=order.priority,
            order_scheduled_start=order.scheduled_start,
            order_scheduled_end=order.scheduled_end,
            item_id=item.id,
            item_no=item.item_no,
            intermediate_type_name=item.intermediate_type_name,
            equipment_id=item.equipment_id,
            planned_quantity=item.planned_quantity,
            unit=item.unit,
            planned_start=item.planned_start,
            planned_end=item.planned_end,
            item_status=item.status,
            item_priority=item.priority,
        ))
    return result


# ═══════════════════════════════════════════
# Demand Allocation
# ═══════════════════════════════════════════

async def create_demand_allocation(
    db: AsyncSession, demand_id: uuid.UUID, payload: DemandAllocationCreate, user: User | None,
) -> DemandAllocation:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status not in ("confirmed", "partial"):
        raise AppException(status_code=400, message="仅 confirmed/partial 状态的需求可分配")
    item = await repo.get_plan_item(db, payload.plan_item_id)
    if not item:
        raise NotFoundException("计划项", str(payload.plan_item_id))
    # 超量分配校验
    existing_das = await repo.get_demand_allocations(db, demand_id)
    current_total = sum(da.allocated_quantity for da in existing_das)
    if current_total + payload.allocated_quantity > demand.demanded_quantity:
        raise AppException(
            status_code=400,
            message=f"分配量超出需求总量：已分配 {current_total}，本次 {payload.allocated_quantity}，需求 {demand.demanded_quantity}",
        )
    da = DemandAllocation(
        demand_id=demand_id,
        plan_item_id=payload.plan_item_id,
        allocated_quantity=payload.allocated_quantity,
        created_by=user.id if user else None,
    )
    db.add(da)
    await db.flush()
    # 重算需求履约量
    all_das = await repo.get_demand_allocations(db, demand_id)
    _recalc_demand_fulfillment(demand, all_das)
    _update_demand_status(demand)
    return da


async def delete_demand_allocation(
    db: AsyncSession, alloc_id: uuid.UUID, user: User | None,
) -> None:
    da = await repo.get_demand_allocation_by_id(db, alloc_id)
    if not da:
        raise NotFoundException("需求分配", str(alloc_id))
    da.is_deleted = True
    da.updated_by = user.id if user else None
    demand = await repo.get_demand(db, da.demand_id)
    if demand:
        all_das = await repo.get_demand_allocations(db, demand.id)
        _recalc_demand_fulfillment(demand, all_das)
        _update_demand_status(demand)
    await db.flush()


# ═══════════════════════════════════════════
# 追溯
# ═══════════════════════════════════════════

async def get_demand_trace(db: AsyncSession, demand_id: uuid.UUID) -> TraceNode:
    """从需求出发，追溯全链路：需求→分配→计划项→分配→批次。"""
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    root = TraceNode(
        type="demand",
        id=demand.id,
        label=f"{demand.demand_no} - {demand.product_name}",
        quantity=demand.demanded_quantity,
        unit=demand.unit,
        status=demand.status,
        children=[],
    )
    da_list = await repo.get_demand_allocations(db, demand_id)
    for da in da_list:
        item = await repo.get_plan_item(db, da.plan_item_id)
        if not item:
            continue
        order = await repo.get_plan_order(db, item.plan_order_id)
        item_node = TraceNode(
            type="plan_item",
            id=item.id,
            label=f"计划项 {order.order_no + '-' + str(item.item_no) if order else '?'} - {item.intermediate_type_name}",
            quantity=item.planned_quantity,
            unit=item.unit,
            status=item.status,
            children=[],
        )
        plan_allocs = await repo.get_plan_allocations_by_item(db, item.id)
        if plan_allocs:
            batch_ids = [a.batch_id for a in plan_allocs]
            batch_map = await repo.get_batches_for_allocations(db, batch_ids)
            for pa in plan_allocs:
                b = batch_map.get(pa.batch_id)
                if b:
                    batch_node = TraceNode(
                        type="batch",
                        id=b.id,
                        label=f"批次 {b.batch_no}",
                        quantity=b.quantity,
                        unit=b.unit,
                        status=b.status,
                        children=[],
                    )
                    item_node.children.append(batch_node)
        root.children.append(item_node)
    return root


# ── 计划项列表（透传 repo） ──


async def list_plan_items(db: AsyncSession, plan_order_id: uuid.UUID) -> list[PlanItem]:
    """获取计划单的所有计划项。ponytail: 直接透传 repo，不额外包装。"""
    return await repo.list_plan_items(db, plan_order_id)


# ── 重新导出供 API 层使用 ──

__all__ = [
    "create_demand",
    "update_demand",
    "delete_demand",
    "confirm_demand",
    "cancel_demand",
    "get_demand_detail",
    "list_demands_paged",
    "create_plan_order",
    "update_plan_order",
    "delete_plan_order",
    "confirm_plan_order",
    "release_plan_order",
    "close_plan_order",
    "get_plan_order_detail",
    "list_plan_orders_paged",
    "create_plan_item",
    "update_plan_item",
    "delete_plan_item",
    "schedule_plan_item",
    "allocate_plan_item",
    "list_plan_items",
    "get_schedule_view",
    "create_demand_allocation",
    "delete_demand_allocation",
    "get_demand_trace",
]
