"""计划中枢业务逻辑：需求、计划单、计划项、分配、下达、追溯。"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.production.models.route import RouteNode
    from app.modules.production.schemas.planning import (
        PlanItemBatchProgress,
        PlanOrderChangeRequest,
    )

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
    PlanOrderChangeLogOut,
    PlanOrderCreate,
    PlanOrderDetailOut,
    PlanOrderUpdate,
    ScheduleViewItem,
    TraceNode,
)
from app.modules.production.service.reminder_service import (
    schedule_plan_released_notification,
)
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

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


def _decrement_batch_no(batch_no: str) -> str:
    """批号末段数字减 1（补位）；无数字段或数字 ≤1 时返回原值。与前端 decrementBatchNo 对齐。

    贪婪首组匹配最后一个数字段（如 ``PO-20260824-001`` 减的是 ``001`` 而不是日期），
    与前端 BATCH_NO_RE（frontend/src/lib/utils.ts）保持同语义。
    """
    m = re.match(r"^(.*)(\d+)(.*)$", batch_no)
    if not m:
        return batch_no
    n = int(m.group(2))
    if n <= 1:
        return batch_no
    return f"{m.group(1)}{n - 1:0{len(m.group(2))}d}{m.group(3)}"


async def _check_batch_no_unique(
    db: AsyncSession, batch_no: str, exclude_item_id: uuid.UUID | None = None,
) -> None:
    """校验批次号在 plan_items 和 batches 表中均不重复。"""
    if not batch_no:
        return
    if await repo.get_plan_item_by_batch_no(db, batch_no, exclude_item_id):
        raise DuplicateException("批次号", batch_no)
    # 已下达的真实批次也不能重复（排除自身对应的批次：若 exclude_item_id 对应已分配的 batch 则放行）
    # ponytail: 直接查 batches 表，不做 item→alloc→batch 的复杂关联排除
    if await repo.get_batch_by_no(db, batch_no):
        raise DuplicateException("批次号", batch_no)


def _stage_config_to_dict(items: list | None) -> list[dict[str, object]] | None:
    """将 StageConfigItem 列表转为 dict 列表，用于 ORM JSONB 持久化。"""
    if not items:
        return None
    return [s.model_dump() for s in items]


def _validate_item_releasable(item: PlanItem) -> None:
    """校验计划项满足下达/分配条件（有工艺路线即可，数量不填不阻塞）。"""
    if not item.route_id:
        raise AppException(
            status_code=400,
            message=f"计划项 {item.item_no} 未指定工艺路线，无法生成批次",
        )


async def _require_route_not_draft(db: AsyncSession, route_id: uuid.UUID) -> None:
    """校验工艺路线存在且非草稿。ponytail: 4 处调用共享。"""
    route = await repo.get_route(db, route_id)
    if not route:
        raise NotFoundException("工艺路线", str(route_id))
    if route.status == "draft":
        raise AppException(status_code=400, message="不能选择草稿状态的工艺路线")


def _merge_chain_batch_status(chain: list[Batch]) -> str:
    """链上批次状态合并：有 in_progress 取 in_progress；全 completed 取 completed；否则取末端。"""
    if any(b.status == "in_progress" for b in chain):
        return "in_progress"
    if all(b.status == "completed" for b in chain):
        return "completed"
    return chain[-1].status


async def _compute_item_batch_progress(
    db: AsyncSession, batch: Batch, route_nodes: list[RouteNode] | None = None,
) -> PlanItemBatchProgress | None:
    """计算批次的生产进度（谱系链合并：子批次继承父批次已完成的工序进度）。

    拆分后不只看末端子批次——父批次已完成的工序计入整条链，进度不因拆分而"倒退"。
    ponytail: 独立函数便于复用，不从 schema 动态 import 避免循环。
    """
    from app.modules.production.schemas.planning import (
        PlanItemBatchProgress,
        RouteNodeBrief,
    )

    item = await _find_plan_item_by_batch(db, batch.id)
    chain = await _collect_chain_batches(db, item) if item else []
    if not chain:
        return PlanItemBatchProgress(
            batch_no=batch.batch_no,
            batch_status=batch.status,
        )
    tip = chain[-1]
    stage, stage_status = await repo.get_chain_node_execution_progress(
        db, [b.id for b in chain],
    )
    if route_nodes is None:
        route_nodes = await repo.get_route_nodes(db, tip.route_id)
    return PlanItemBatchProgress(
        batch_no=tip.batch_no,
        batch_status=_merge_chain_batch_status(chain),
        latest_stage=stage,
        latest_stage_status=stage_status,
        route_nodes=[
            RouteNodeBrief(name=n.name, stage_name=n.stage_name)
            for n in route_nodes
        ] or None,
    )


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
            dao.intermediate_type_name = item.product_name
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
    await _require_route_not_draft(db, payload.route_id)
    order = PlanOrder(
        order_no=payload.order_no,
        title=payload.title,
        product_id=payload.product_id,
        route_id=payload.route_id,
        stage_config=_stage_config_to_dict(payload.stage_config),
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
    # 校验工艺路线非 draft
    if "route_id" in update_data and update_data["route_id"] is not None:
        await _require_route_not_draft(db, update_data["route_id"])
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
    item_batch_nos: dict[uuid.UUID, str] = {}
    for item in items:
        _validate_item_releasable(item)
        base_no = item.batch_no if item.batch_no else f"{order.order_no}-{item.item_no}"
        batch_no = await _ensure_unique_batch_no(db, base_no)
        batch = Batch(
            batch_no=batch_no,
            product_id=item.product_id,
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
        item_batch_nos[item.id] = batch.batch_no
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
    # 飞书提醒：计划单下达（收集在事务内，发送为后台尽力而为）
    await schedule_plan_released_notification(db, order, items, item_batch_nos)
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def close_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status not in ("confirmed", "released", "completed"):
        raise AppException(status_code=400, message="仅 confirmed/released/completed 状态的计划单可关闭")
    order.status = "closed"
    order.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_order(db, order_id)
    assert refreshed is not None
    return refreshed


async def change_plan_order(
    db: AsyncSession, order_id: uuid.UUID, payload: PlanOrderChangeRequest, user: User | None,
) -> PlanOrder:
    """对已下达的计划单执行变更。"""
    from app.modules.production.models.planning import PlanChangeLog

    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "released":
        raise AppException(status_code=400, message="仅 released 状态的计划单可变更")

    # ── 预处理：收集涉及 PlanItem，批量查 Batch 状态 ──
    upsert_ids = [i.id for i in (payload.items_upsert or []) if i.id is not None]
    delete_ids = payload.items_delete or []
    all_item_ids = upsert_ids + delete_ids
    item_batch_map = await repo.get_batches_by_plan_items(db, all_item_ids) if all_item_ids else {}
    # 删除项也需要查（可能没有 allocation）
    for item_id in delete_ids:
        if item_id not in item_batch_map:
            allocs = await repo.get_plan_allocations_by_item(db, item_id)
            if allocs:
                batch_stmt = select(Batch).where(
                    Batch.id == allocs[0].batch_id, Batch.is_deleted == False  # noqa: E712
                )
                batch = (await db.execute(batch_stmt)).scalar_one_or_none()
                if batch:
                    item_batch_map[item_id] = batch

    # 校验不可变更的项（batch 已进入生产）
    blocked_ids: set[uuid.UUID] = set()
    for item_id, batch in item_batch_map.items():
        if batch.status not in ("scheduled", "cancelled"):
            blocked_ids.add(item_id)

    # ── 删除计划项 ──
    if payload.items_delete:
        for item_id in payload.items_delete:
            if item_id in blocked_ids:
                item = await repo.get_plan_item(db, item_id)
                item_no = item.item_no if item else "?"
                raise AppException(
                    status_code=400,
                    message=f"计划项 {item_no} 对应批次已进入生产，无法删除",
                )
            batch = item_batch_map.get(item_id)
            if batch:
                batch.status = "cancelled"
                batch.updated_by = user.id if user else None
            plan_allocs = await repo.get_plan_allocations_by_item(db, item_id)
            for pa in plan_allocs:
                pa.is_deleted = True
                pa.updated_by = user.id if user else None
            item = await repo.get_plan_item(db, item_id)
            if item:
                item.is_deleted = True
                item.updated_by = user.id if user else None

    # ── 更新/新增计划项 ──
    if payload.items_upsert:
        for ci in payload.items_upsert:
            if ci.id is not None:
                # 更新：批次生产中 → 跳过，不报错（删除仍会报错）
                if ci.id in blocked_ids:
                    continue
                item = await repo.get_plan_item(db, ci.id)
                if not item:
                    raise NotFoundException("计划项", str(ci.id))
                if ci.batch_no is not None and ci.batch_no != item.batch_no:
                    await _check_batch_no_unique(db, ci.batch_no, ci.id)
                update_data = ci.model_dump(exclude_unset=True, exclude={"id"})
                qty_changed = "planned_quantity" in update_data
                for field, value in update_data.items():
                    setattr(item, field, value)
                item.updated_by = user.id if user else None
                if qty_changed:
                    batch = item_batch_map.get(ci.id)
                    if batch:
                        batch.quantity = ci.planned_quantity
                        batch.updated_by = user.id if user else None
                    plan_allocs = await repo.get_plan_allocations_by_item(db, ci.id)
                    for pa in plan_allocs:
                        pa.allocated_quantity = ci.planned_quantity
                        pa.updated_by = user.id if user else None
            else:
                # 新增
                product_id = ci.product_id if ci.product_id else order.product_id
                if not product_id:
                    raise AppException(status_code=400, message="新增计划项缺少 product_id")
                route_id = ci.route_id if ci.route_id else order.route_id
                if not route_id:
                    raise AppException(status_code=400, message="新增计划项缺少 route_id")
                batch_no_input = ci.batch_no or ""
                if batch_no_input:
                    await _check_batch_no_unique(db, batch_no_input)
                max_no = await repo.get_max_item_no(db, order_id)
                item_no = max_no + 1
                # 未显式配置工段时长时不快照计划单 stage_config，展示时继承（改配置自动生效）
                stage_durations = _stage_config_to_dict(ci.stage_durations)
                new_item = PlanItem(
                    plan_order_id=order_id,
                    item_no=item_no,
                    product_id=product_id,
                    product_name=ci.product_name or "",
                    route_id=route_id,
                    equipment_id=ci.equipment_id,
                    planned_quantity=ci.planned_quantity,
                    unit=ci.unit,
                    batch_no=ci.batch_no,
                    priority=ci.priority or "medium",
                    remark=ci.remark,
                    stage_durations=stage_durations,
                    sort_order=ci.sort_order or 0,
                    status="allocated",
                    created_by=user.id if user else None,
                )
                db.add(new_item)
                await db.flush()
                base_no = ci.batch_no if ci.batch_no else f"{order.order_no}-{item_no}"
                new_batch_no = await _ensure_unique_batch_no(db, base_no)
                batch = Batch(
                    batch_no=new_batch_no,
                    product_id=product_id,
                    route_id=route_id,
                    status="scheduled",
                    quantity=ci.planned_quantity,
                    unit=ci.unit,
                    creation_type="plan",
                    plan_version=order.plan_version + 1,
                    created_by=user.id if user else None,
                )
                db.add(batch)
                await db.flush()
                alloc = PlanAllocation(
                    plan_item_id=new_item.id,
                    batch_id=batch.id,
                    allocated_quantity=ci.planned_quantity,
                    created_by=user.id if user else None,
                )
                db.add(alloc)

    # ── 更新计划单头部 ──
    update_data = payload.model_dump(
        exclude_unset=True, exclude={"change_reason", "items_upsert", "items_delete"},
    )
    for field, value in update_data.items():
        setattr(order, field, value)
    order.plan_version += 1
    order.updated_by = user.id if user else None

    # ── 写变更日志 ──
    log = PlanChangeLog(
        plan_order_id=order_id,
        plan_version=order.plan_version,
        change_reason=payload.change_reason,
        changed_by=user.id if user else None,
    )
    db.add(log)

    await db.flush()

    # ── 需求履约重算 ──
    all_items = await repo.list_plan_items(db, order_id)
    if all_items:
        item_ids = [i.id for i in all_items]
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
    # 同一计划单的 item 通常共享 route_id，按路线缓存节点查询避免 N 次重复 SELECT
    route_nodes_cache: dict[uuid.UUID, list[RouteNode]] = {}
    for item in items:
        pio = PlanItemOut.model_validate(item)
        # 填充 allocations
        plan_allocs = await repo.get_plan_allocations_by_item(db, item.id)
        pio.allocations = []
        if plan_allocs:
            batch_ids = [a.batch_id for a in plan_allocs]
            batch_map = await repo.get_batches_for_allocations(db, batch_ids)
            # 注入 batch_progress（复用已有 batch_map）
            first_batch = batch_map.get(plan_allocs[0].batch_id) if batch_map else None
            if first_batch:
                if first_batch.route_id not in route_nodes_cache:
                    route_nodes_cache[first_batch.route_id] = await repo.get_route_nodes(
                        db, first_batch.route_id,
                    )
                pio.batch_progress = await _compute_item_batch_progress(
                    db, first_batch, route_nodes_cache[first_batch.route_id],
                )
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
            dao.intermediate_type_name = item.product_name
            pio.demand_allocations.append(dao)
        item_outs.append(pio)
    detail = PlanOrderDetailOut.model_validate(order)
    detail.items = item_outs
    # 注入变更日志
    logs = await repo.get_change_logs(db, order_id)
    log_outs: list[PlanOrderChangeLogOut] = []
    for log_entry in logs:
        lo = PlanOrderChangeLogOut.model_validate(log_entry)
        lo.changed_by_name = ""  # ponytail: 暂不查 identity 姓名
        log_outs.append(lo)
    detail.change_logs = log_outs
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
    if order.status not in ("draft", "confirmed"):
        raise AppException(status_code=400, message="仅未下达的计划单可添加计划项")
    await _check_batch_no_unique(db, payload.batch_no)
    max_no = await repo.get_max_item_no(db, order_id)
    item_no = max_no + 1
    # 继承：若未传则使用计划单的 product_id / route_id
    product_id = payload.product_id if payload.product_id else order.product_id
    route_id = payload.route_id if payload.route_id else order.route_id
    # 校验工艺路线非 draft
    if route_id:
        await _require_route_not_draft(db, route_id)
    # 未显式配置工段时长时不快照计划单 stage_config，展示时继承（改配置自动生效）
    stage_durations = _stage_config_to_dict(payload.stage_durations)
    item = PlanItem(
        plan_order_id=order_id,
        item_no=item_no,
        product_id=product_id,
        product_name=payload.product_name,
        route_id=route_id,
        equipment_id=payload.equipment_id,
        planned_quantity=payload.planned_quantity,
        unit=payload.unit,
        batch_no=payload.batch_no,
        priority=payload.priority,
        remark=payload.remark,
        stage_durations=stage_durations,
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
    if payload.batch_no is not None:
        await _check_batch_no_unique(db, payload.batch_no, item.id)
    update_data = payload.model_dump(exclude_unset=True)
    # 校验工艺路线非 draft
    if "route_id" in update_data and update_data["route_id"] is not None:
        await _require_route_not_draft(db, update_data["route_id"])
    for field, value in update_data.items():
        setattr(item, field, value)
    item.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_plan_item(db, item_id)
    assert refreshed is not None
    return refreshed


async def delete_plan_item(
    db: AsyncSession, item_id: uuid.UUID, user: User | None, shift: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """软删除计划项，不做状态限制。shift=True 时后续批次号前移补位。

    补位范围 = 同计划单列表中删除项之后的各项（与前端预览一致），
    仅处理 draft/scheduled 状态（已生成批次的项改名会导致批号脱钩，跳过）。
    目标批号被占用时跳过该项，删除本身不受影响。
    """
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))

    shifted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    # 补位定位必须在删除前（软删除后该项不再出现在同单列表）：
    # 取同单列表找到删除位置，后续项 = 删除项之后的各项。
    following: list[PlanItem] = []
    if shift:
        siblings = await repo.list_plan_items(db, item.plan_order_id)
        deleted_idx = next((i for i, s in enumerate(siblings) if s.id == item_id), None)
        if deleted_idx is not None:
            following = siblings[deleted_idx + 1:]

    item.is_deleted = True
    item.updated_by = user.id if user else None
    await db.flush()

    if not following:
        return {"shifted": shifted, "skipped": skipped}

    movable: list[tuple[PlanItem, str]] = []
    for sib in following:
        if not sib.batch_no or sib.status not in ("draft", "scheduled"):
            continue
        new_no = _decrement_batch_no(sib.batch_no)
        if new_no != sib.batch_no:
            movable.append((sib, new_no))

    # 一次性预取占用号，内存中逐步让出/占用（3 次查询替代原先 2N+1 次）：
    # 计划项占用 = 后续项当前批号 + 全表计划项对候选新号的占用（list_plan_item_nos，
    # 与创建/编辑的全局唯一校验 get_plan_item_by_batch_no 同口径；被删项已软删除
    # 并 flush，其批号自动让出）；真实批次占用 = 候选新号。候选新号自身不预置
    # 占用——是否被占由「其他行让出 + 计划项/真实批次」决定，保持逐项顺序语义。
    original_nos = [sib.batch_no for sib in following if sib.batch_no]
    candidate_nos = [n for _, n in movable]
    occupied = (
        set(original_nos)
        | await repo.list_plan_item_nos(db, candidate_nos)
        | await repo.list_batch_nos(db, candidate_nos)
    )
    # 多轮补位：后续项按列表序（排程时间序）处理，目标被尚未让位的兄弟项占住时
    # 先跳过，等该兄弟项在后续轮次让出后再补；只有真正被外部占用（其他计划单的
    # 计划项/真实批次）的目标才会进 skipped。每轮至少推进一项，否则终止。
    pending = list(movable)
    while pending:
        progressed = False
        still_blocked: list[tuple[PlanItem, str]] = []
        for sib, new_no in pending:
            old_no = sib.batch_no
            assert old_no is not None  # movable 构造时已过滤空批号
            if new_no in occupied:
                still_blocked.append((sib, new_no))
                continue
            sib.batch_no = new_no
            sib.updated_by = user.id if user else None
            occupied.discard(old_no)
            occupied.add(new_no)
            shifted.append({"item_id": str(sib.id), "batch_no": new_no})
            progressed = True
        if not progressed:
            skipped.extend(
                {"item_id": str(sib.id), "batch_no": sib.batch_no or ""}
                for sib, _ in still_blocked
            )
            break
        pending = still_blocked
    await db.flush()
    return {"shifted": shifted, "skipped": skipped}


async def schedule_plan_item(
    db: AsyncSession, item_id: uuid.UUID, payload: PlanItemScheduleIn, user: User | None,
) -> tuple[PlanItem, list[dict[str, object]]]:
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
    warnings: list[dict[str, object]] = []
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
                    "product_name": c.product_name,
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
    _validate_item_releasable(item)
    order = await repo.get_plan_order(db, item.plan_order_id)
    if not order:
        raise NotFoundException("计划单", str(item.plan_order_id))
    base_no = item.batch_no if item.batch_no else f"{order.order_no}-{item.item_no}"
    batch_no = await _ensure_unique_batch_no(db, base_no)
    batch = Batch(
        batch_no=batch_no,
        product_id=item.product_id,
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


async def sync_plan_item_status(db: AsyncSession, batch_id: uuid.UUID) -> None:
    """批次/工序状态变化后联动计划项：allocated → in_progress → completed。

    判定规则见 docs/superpowers/specs/2026-08-03-plan-item-batch-status-sync-design.md：
    计划项配置工段 S 内全部工序节点，在单线谱系链（跳过 cancelled）上有 completed
    执行即完成。cancelled 批次不打断判定、其节点不计。
    """
    batch = await repo.get_batch(db, batch_id)
    if not batch:
        return
    item = await _find_plan_item_by_batch(db, batch_id)
    if not item or item.status not in ("allocated", "in_progress"):
        return
    changed = False
    chain = await _collect_chain_batches(db, item)
    if item.status == "allocated":
        # 开工判定以谱系根批次为准：同步触发点可能是子批次（含已报废的），
        # 但 allocated → in_progress 取决于根批次是否已开工
        root = chain[0] if chain else batch
        if root.status == "in_progress":
            item.status = "in_progress"
            changed = True
    if await _is_stage_covered(db, item, chain):
        item.status = "completed"
        changed = True
    if changed:
        item.updated_by = None
        await db.flush()
        # 铁律：UPDATE 后 select re-fetch，刷新 updated_at 等 onupdate 字段
        refreshed = await repo.get_plan_item(db, item.id)
        assert refreshed is not None


async def _find_plan_item_by_batch(
    db: AsyncSession, batch_id: uuid.UUID,
) -> PlanItem | None:
    """batch → 非删除 PlanAllocation → PlanItem；谱系子批次沿 BatchLink 回溯到有分配的祖先。"""
    current_id = batch_id
    while current_id:
        allocs = await repo.get_plan_allocations_by_batch(db, current_id)
        if allocs:
            return await repo.get_plan_item(db, allocs[0].plan_item_id)
        current_id = await repo.get_parent_batch_id(db, current_id)
    return None


async def _item_stage_names(db: AsyncSession, item: PlanItem) -> set[str]:
    """计划项配置工段集合；为空时继承计划单 stage_config（JSONB dict 列表）。"""
    if item.stage_durations:
        return {s["stage_name"] for s in item.stage_durations if s.get("stage_name")}
    order = await repo.get_plan_order(db, item.plan_order_id)
    if order and order.stage_config:
        return {s["stage_name"] for s in order.stage_config if s.get("stage_name")}
    return set()


async def _is_stage_covered(
    db: AsyncSession, item: PlanItem, chain: list[Batch] | None = None,
) -> bool:
    """判定：配置工段 S 内全部工序节点，在谱系链（跳过 cancelled）上有 completed 执行。"""
    nodes = await repo.get_route_nodes(db, item.route_id)
    if not nodes:
        return False
    stages = await _item_stage_names(db, item)
    target_ids = {
        n.id for n in nodes if not stages or (n.stage_name and n.stage_name in stages)
    }
    if not target_ids:
        return False
    if chain is None:
        chain = await _collect_chain_batches(db, item)
    if not chain:
        return False
    completed_ids = await repo.get_completed_node_ids_by_batches(
        db, [b.id for b in chain],
    )
    return target_ids <= completed_ids


async def _collect_chain_batches(db: AsyncSession, item: PlanItem) -> list[Batch]:
    """沿单线谱系链收集有效（非 cancelled）批次：根批次 → 唯一有效子批次。
    cancelled 批次不打断判定、其节点不计：跳过并继续下钻。
    ponytail: 单线假设，同层出现多个子批次时取第一个（业务上不会发生）。"""
    allocs = await repo.get_plan_allocations_by_item(db, item.id)
    if not allocs:
        return []
    chain: list[Batch] = []
    current = await repo.get_batch(db, allocs[0].batch_id)
    while current:
        if current.status != "cancelled":
            chain.append(current)
        child_ids = await repo.get_child_batch_ids(db, current.id)
        if not child_ids:
            break
        children = await repo.get_batches_by_ids(db, child_ids)
        if not children:
            break
        valid = [b for b in children if b.status != "cancelled"]
        if len(valid) > 1:
            logger.warning(
                "计划项 %s 谱系出现多有效子批次，仅追踪第一个（单线假设被打破）",
                item.item_no,
            )
        if valid:
            current = valid[0]
            continue
        # 全部子批次已报废：跳过 cancelled 继续下钻，不打断判定
        current = children[0]
    return chain


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
            product_id=item.product_id,
            product_name=item.product_name,
            equipment_id=item.equipment_id,
            planned_quantity=item.planned_quantity,
            unit=item.unit,
            batch_no=item.batch_no,
            route_id=item.route_id,
            stage_durations=item.stage_durations or order.stage_config,
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
            label=f"计划项 {order.order_no + '-' + str(item.item_no) if order else '?'} - {item.product_name}",
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
    "change_plan_order",
    "get_plan_order_detail",
    "list_plan_orders_paged",
    "create_plan_item",
    "update_plan_item",
    "delete_plan_item",
    "schedule_plan_item",
    "allocate_plan_item",
    "sync_plan_item_status",
    "list_plan_items",
    "get_schedule_view",
    "create_demand_allocation",
    "delete_demand_allocation",
    "get_demand_trace",
]
