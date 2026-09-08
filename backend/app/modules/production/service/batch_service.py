"""批次生命周期、derive/merge 谱系写入。谱系一致性只在本文件维护。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.production import repository as repo
from app.modules.production.models import Batch, BatchLink
from app.modules.production.schemas import (
    BatchCreate,
    BatchDetailOut,
    BatchNoUpdateIn,
    BatchOwnerTransferIn,
    DeriveIn,
    EquipmentSnapshotOut,
    ExecutionOut,
    FieldValueOut,
    MergeIn,
)
from app.modules.production.service.assignment_service import (
    check_operator_access,
    require_batch_owner_access,
    require_operator_access,
)
from app.modules.production.service.computed_service import expand_computed_fields
from app.modules.production.service.execution_service import (
    compute_missing_required_fields,
)
from app.modules.production.service.planning_service import (
    _check_batch_no_unique,
    _find_plan_item_by_batch,
    sync_plan_item_status,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User
from app.platform.permission.deps import get_user_permissions


async def _check_boundary_stage_permission(
    db: AsyncSession,
    user: User,
    edge_id: uuid.UUID,
    route_id: uuid.UUID,
) -> None:
    """校验用户对边界边接收工段（终点工序）的操作权限。

    边界边的 to_node 即子批次接收工段的首个工序，
    只有该工段或该节点的负责人才有权从此边界派生/合并子批次，
    与工作台 pending_receive 的显示口径一致（共享认领池）。
    使用 repository 层查询而非原始 select，保持架构一致性。
    """
    edge = await repo.get_edge(db, edge_id)
    if not edge:
        return
    nodes = await repo.get_nodes_by_ids(db, [edge.to_node_id])
    to_node = nodes[0] if nodes else None
    if to_node is None:
        # 接收节点已被删除（路线重发布后残留边）：不放行，防止绕过工段权限
        raise ForbiddenException("接收工段不存在，无权操作")
    # 历史图豁免：接收工段未分组时跳过（与旧 from_node 豁免同语义）
    if to_node.stage_name:
        await require_operator_access(
            db, user.id, to_node.id, route_id, to_node.stage_name, batch=None,
        )


async def _get_batch_or_404(db: AsyncSession, batch_id: uuid.UUID) -> Batch:
    batch = await repo.get_batch(db, batch_id)
    if not batch:
        raise NotFoundException("批次", str(batch_id))
    return batch


async def create_batch(
    db: AsyncSession, payload: BatchCreate, user: User | None
) -> Batch:
    route = await repo.get_route(db, payload.route_id)
    if not route:
        raise NotFoundException("工艺路线", str(payload.route_id))
    if route.status != "published":
        raise AppException(status_code=400, message="只能在 published 路线上创建批次")
    if route.product_id != payload.product_id:
        raise AppException(status_code=400, message="路线不属于该产品")
    # 批号空间全局唯一：plan_items 预分配号 + batches（与计划项创建/编辑同口径）
    await _check_batch_no_unique(db, payload.batch_no)
    batch = Batch(
        batch_no=payload.batch_no,
        product_id=payload.product_id,
        route_id=payload.route_id,
        status="pending",
        quantity=payload.quantity,
        unit=payload.unit,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(batch)
    await db.flush()
    return batch


async def _validate_boundary(
    db: AsyncSession,
    parent: Batch,
    edge_id: uuid.UUID | None,
    deviation_reason: str | None,
) -> tuple[uuid.UUID | None, bool]:
    """校验边界流转，返回 (entry_node_id, is_deviation)。"""
    if parent.status not in ("in_progress", "completed"):
        raise AppException(
            status_code=400, message="仅 in_progress/completed 的批次可作为父批次"
        )
    if edge_id is None:
        if not deviation_reason:
            raise AppException(
                status_code=400, message="未指定边界边时必须提供偏离原因"
            )
        return None, True
    edge = await repo.get_edge(db, edge_id)
    if not edge or edge.route_id != parent.route_id:
        raise NotFoundException("边界边", str(edge_id))
    if not edge.is_batch_boundary:
        raise AppException(status_code=400, message="指定的边不是批次边界")
    completed = await repo.completed_node_ids(db, parent.id)
    if edge.from_node_id not in completed:
        raise AppException(
            status_code=400, message="父批次尚未完成边界边起点工序，不能流转"
        )
    return edge.to_node_id, False


async def derive_batches(
    db: AsyncSession, parent_id: uuid.UUID, payload: DeriveIn, user: User | None
) -> list[Batch]:
    """分裂 1→N / 1→1 换号：创建子批次并写谱系。"""
    parent = await _get_batch_or_404(db, parent_id)
    entry_node_id, is_deviation = await _validate_boundary(
        db, parent, payload.edge_id, payload.deviation_reason
    )
    # 工段权限校验
    if user and payload.edge_id and not is_deviation:
        await _check_boundary_stage_permission(
            db, user, payload.edge_id, parent.route_id,
        )
    nos = [c.batch_no for c in payload.children]
    if len(nos) != len(set(nos)):
        raise AppException(status_code=400, message="子批次批号重复")
    for child_in in payload.children:
        if await repo.get_batch_by_no(db, child_in.batch_no):
            raise DuplicateException("批号", child_in.batch_no)
    children: list[Batch] = []
    for child_in in payload.children:
        child = Batch(
            id=uuid.uuid4(),  # 显式生成：flush 前 BatchLink 就要引用它
            batch_no=child_in.batch_no,
            product_id=parent.product_id,
            route_id=parent.route_id,
            status="pending",
            quantity=child_in.quantity,
            unit=child_in.unit or parent.unit,
            entry_node_id=entry_node_id,
            owner_user_id=user.id if user else None,
            owner_name=user.name if user else None,
            created_by=user.id if user else None,
        )
        db.add(child)
        children.append(child)
        db.add(
            BatchLink(
                parent_batch_id=parent.id,
                child_batch_id=child.id,
                edge_id=payload.edge_id,
                allocated_qty=child_in.quantity,
                is_deviation=is_deviation,
                deviation_reason=payload.deviation_reason,
                created_by=user.id if user else None,
            )
        )
    await db.flush()
    await record_audit_log(
        db,
        action="production.batch.derive",
        user=user,
        resource_type="batch",
        resource_id=parent.id,
        extra={"children": [c.batch_no for c in children]},
    )
    await sync_plan_item_status(db, parent.id)
    return children


async def merge_batches(
    db: AsyncSession, payload: MergeIn, user: User | None
) -> Batch:
    """合并 N→1：多个父批次汇成一个新批次。校验规则同 derive，对每个父批次分别校验。"""
    parents: list[Batch] = []
    entry_node_id: uuid.UUID | None = None
    is_deviation = False
    pids = [p.batch_id for p in payload.parents]
    if len(pids) != len(set(pids)):
        raise AppException(status_code=400, message="合并的父批次重复")
    for p_in in payload.parents:
        parent = await _get_batch_or_404(db, p_in.batch_id)
        entry, dev = await _validate_boundary(
            db, parent, payload.edge_id, payload.deviation_reason
        )
        entry_node_id, is_deviation = entry, dev
        parents.append(parent)
    route_ids = {p.route_id for p in parents}
    if len(route_ids) != 1:
        raise AppException(status_code=400, message="合并的父批次必须属于同一条路线")
    # 工段权限校验
    if user and payload.edge_id and not is_deviation:
        route_id = next(iter(route_ids))
        await _check_boundary_stage_permission(
            db, user, payload.edge_id, route_id,
        )
    if await repo.get_batch_by_no(db, payload.batch_no):
        raise DuplicateException("批号", payload.batch_no)
    child = Batch(
        id=uuid.uuid4(),  # 显式生成：flush 前 BatchLink 就要引用它
        batch_no=payload.batch_no,
        product_id=parents[0].product_id,
        route_id=parents[0].route_id,
        status="pending",
        quantity=payload.quantity,
        unit=payload.unit or parents[0].unit,
        entry_node_id=entry_node_id,
        owner_user_id=user.id if user else None,
        owner_name=user.name if user else None,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(child)
    for p_in, parent in zip(payload.parents, parents, strict=True):
        db.add(
            BatchLink(
                parent_batch_id=parent.id,
                child_batch_id=child.id,
                edge_id=payload.edge_id,
                allocated_qty=p_in.allocated_qty,
                is_deviation=is_deviation,
                deviation_reason=payload.deviation_reason,
                created_by=user.id if user else None,
            )
        )
    await db.flush()
    await record_audit_log(
        db,
        action="production.batch.merge",
        user=user,
        resource_type="batch",
        resource_id=child.id,
        extra={"parents": [p.batch_no for p in parents]},
    )
    return child


async def _missing_required_fields(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[tuple[str, str]]:
    """已结束工序缺填的必填字段（end 阶段），返回 (工序名, 字段名) 列表。"""
    executions = await repo.list_executions(db, batch_id)
    missing_by_exec = await compute_missing_required_fields(db, executions)
    if not missing_by_exec:
        return []
    nodes = await repo.get_nodes_by_ids(db, list({e.node_id for e in executions}))
    node_names = {n.id: n.name for n in nodes}
    ex_by_id = {e.id: e for e in executions}
    missing: list[tuple[str, str]] = []
    for exec_id, fields in missing_by_exec.items():
        ex = ex_by_id.get(exec_id)
        node_name = node_names.get(ex.node_id, ex.node_id.hex[:8]) if ex else ""
        for f in fields:
            missing.append((node_name, f.field_label))
    return missing


async def complete_batch(
    db: AsyncSession, batch_id: uuid.UUID, user: User | None
) -> Batch:
    batch = await _get_batch_or_404(db, batch_id)
    if batch.status != "in_progress":
        raise AppException(status_code=400, message="仅 in_progress 的批次可完成")

    # 权限校验必须在业务校验之前，避免信息泄露
    if user:
        perms = await get_user_permissions(str(user.id), db)
        if "production:batch:submit" not in perms:
            # DB 层直接查最后一个完成的执行，避免全量拉取后 Python 排序
            last_ex = await repo.get_last_completed_execution(db, batch_id)
            if last_ex:
                route_nodes = await repo.get_nodes_by_ids(db, [last_ex.node_id])
                node = route_nodes[0] if route_nodes else None
                # 与 start/complete_execution 同口径：工序负责人豁免归属限制
                await require_operator_access(
                    db, user.id, last_ex.node_id, batch.route_id,
                    node.stage_name if node else None,
                    batch=batch,
                )
            else:
                await require_batch_owner_access(user.id, batch)

    if not await repo.completed_node_ids(db, batch_id):
        raise AppException(status_code=400, message="批次没有任何已完成的工序")
    missing = await _missing_required_fields(db, batch_id)
    if missing:
        labels = ", ".join(f"{n}·{f}" for n, f in missing)
        raise AppException(
            status_code=400, message=f"以下工序的必填字段尚未上报，无法完成批次: {labels}"
        )
    batch.status = "completed"
    batch.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_batch(db, batch_id)
    assert refreshed is not None
    return refreshed


async def cancel_batch(
    db: AsyncSession, batch_id: uuid.UUID, user: User | None
) -> Batch:
    batch = await _get_batch_or_404(db, batch_id)
    if batch.status in ("completed", "cancelled"):
        raise AppException(status_code=400, message="已完成或已报废的批次不能报废")
    batch.status = "cancelled"
    batch.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="production.batch.cancel",
        user=user,
        resource_type="batch",
        resource_id=batch.id,
    )
    refreshed = await repo.get_batch(db, batch_id)
    assert refreshed is not None
    await sync_plan_item_status(db, batch.id)
    return refreshed


async def _require_submit_permission(db: AsyncSession, user: User | None) -> None:
    """转移负责人/修改批号共用的硬权限门禁（production:batch:submit，无工段豁免）。"""
    if user is None:
        raise ForbiddenException("未登录，无法执行操作")
    perms = await get_user_permissions(str(user.id), db)
    if "production:batch:submit" not in perms:
        raise ForbiddenException("缺少 production:batch:submit 权限")


async def transfer_batch_owner(
    db: AsyncSession, batch_id: uuid.UUID, payload: BatchOwnerTransferIn, user: User | None
) -> Batch:
    """转移/清空批次负责人（复用 production:batch:submit 权限）。

    归属校验、工作台「我的批次」、产线兜底、飞书提醒均实时读
    batch.owner_user_id，改字段即完成权限转移；各工序的单次执行负责人
    （execution.owner_id）不受影响。终态批次不可转移（无操作权可转，
    且避免篡改历史归属）。
    """
    batch = await _get_batch_or_404(db, batch_id)
    if batch.status in ("completed", "cancelled"):
        raise AppException(status_code=400, message="批次已结束，不能转移负责人")

    await _require_submit_permission(db, user)
    assert user is not None  # _require_submit_permission 已拒绝匿名用户

    old_owner = {
        "owner_user_id": str(batch.owner_user_id) if batch.owner_user_id else None,
        "owner_name": batch.owner_name,
    }
    if payload.owner_user_id is not None:
        if payload.owner_user_id == batch.owner_user_id:
            raise AppException(status_code=400, message="负责人未变化")
        stmt = select(User).where(
            User.id == payload.owner_user_id,
            User.is_deleted == False,  # noqa: E712
        )
        new_owner = (await db.execute(stmt)).scalar_one_or_none()
        if new_owner is None:
            raise NotFoundException("用户", str(payload.owner_user_id))
        batch.owner_user_id = new_owner.id
        batch.owner_name = new_owner.name
    else:
        # 清空负责人：恢复无主共享状态（工段内可操作，首开工会被认领）
        if batch.owner_user_id is None:
            raise AppException(status_code=400, message="负责人未变化")
        batch.owner_user_id = None
        batch.owner_name = None
    batch.updated_by = user.id
    await db.flush()
    await record_audit_log(
        db,
        action="production.batch.transfer_owner",
        user=user,
        resource_type="batch",
        resource_id=batch.id,
        old_value=old_owner,
        new_value={
            "owner_user_id": str(batch.owner_user_id) if batch.owner_user_id else None,
            "owner_name": batch.owner_name,
        },
        extra={"batch_no": batch.batch_no},
    )
    # 重新查询返回：updated_at 带 onupdate，flush 后属性过期，
    # 直接序列化原对象会触发同步惰性加载（MissingGreenlet）
    refreshed = await repo.get_batch(db, batch_id)
    assert refreshed is not None
    return refreshed


async def rename_batch_no(
    db: AsyncSession, batch_id: uuid.UUID, payload: BatchNoUpdateIn, user: User | None
) -> Batch:
    """修改批次号（复用 production:batch:submit 权限，不限批次状态）。

    批号是批次身份级数据：展示/溯源/MCP 批号查询均实时读库，改名自动跟随；
    中间体产出记录已固化的批号快照（intermediate_batch_no）不回写。
    唯一性同计划项创建/编辑口径（batches ∪ plan_items 预分配号）；
    对应计划项的批号种子未被计划员改过时同步回写。
    """
    batch = await _get_batch_or_404(db, batch_id)

    await _require_submit_permission(db, user)
    assert user is not None  # _require_submit_permission 已拒绝匿名用户

    new_no = payload.batch_no
    if new_no == batch.batch_no:
        raise AppException(status_code=400, message="批次号未变化")
    # 批号空间全局唯一：查 plan_items 预分配号 + batches（排除自身计划项，
    # 与 update_plan_item 同口径；计划员已把种子改成 new_no 时也放行）
    item = await _find_plan_item_by_batch(db, batch_id)
    await _check_batch_no_unique(db, new_no, exclude_item_id=item.id if item else None)

    old_no = batch.batch_no
    batch.batch_no = new_no
    batch.updated_by = user.id
    # 回写计划项批号：种子仍等于旧批号才同步（已改写说明是留给未来下达的新号）
    if item and item.batch_no == old_no:
        item.batch_no = new_no
        item.updated_by = user.id
    await db.flush()
    await record_audit_log(
        db,
        action="production.batch.rename_no",
        user=user,
        resource_type="batch",
        resource_id=batch.id,
        old_value={"batch_no": old_no},
        new_value={"batch_no": new_no},
        extra={"batch_no": new_no, "status": batch.status},
    )
    # 重新查询返回：updated_at 带 onupdate，flush 后属性过期，
    # 直接序列化原对象会触发同步惰性加载（MissingGreenlet）
    refreshed = await repo.get_batch(db, batch_id)
    assert refreshed is not None
    return refreshed


async def get_batch_detail(
    db: AsyncSession, batch_id: uuid.UUID, user: User | None = None,
) -> BatchDetailOut:
    """批次详情 = 批次 + 执行时间线（含设备快照、字段值、工序名）。

    user 给定时按当前用户填充 can_complete / executions[].can_backfill
    （权限 + 状态的"现在就能做"语义，与 complete_batch /
    backfill_execution_fields 的授权口径一致）。前端据此显示按钮，
    写接口仍各自校验兜底——标志只是 UI 预判，不是新的授权面。
    """
    batch = await _get_batch_or_404(db, batch_id)
    executions = await repo.list_executions(db, batch_id)
    exec_ids = [e.id for e in executions]
    equipments = await repo.get_equipments_by_executions(db, exec_ids)
    values = await repo.get_field_values_by_executions(db, exec_ids)
    nodes = await repo.get_nodes_by_ids(db, list({e.node_id for e in executions}))
    node_names = {n.id: n.name for n in nodes}
    node_stage_names = {n.id: n.stage_name for n in nodes}

    has_submit = False
    if user is not None:
        perms = await get_user_permissions(str(user.id), db)
        has_submit = "production:batch:submit" in perms
    # 补录仅批次结束前可用（completed/cancelled 均禁止，与 backfill_execution_fields 一致）
    batch_backfillable = batch.status not in ("completed", "cancelled")

    async def _can_backfill(e) -> bool:
        if user is None or not batch_backfillable or e.status != "completed":
            return False
        if has_submit:
            return True
        return await check_operator_access(
            db, user.id, e.node_id, batch.route_id,
            node_stage_names.get(e.node_id), batch=batch, execution=e,
        )

    async def _can_complete() -> bool:
        if user is None or batch.status != "in_progress":
            return False
        if has_submit:
            return True
        # 与 complete_batch 同口径：最后一个完成的执行的 node 做归属判定，
        # 不传 execution——完成批次不吃单次执行负责人豁免
        last_ex = max(
            (e for e in executions
             if e.status == "completed" and e.finished_at is not None),
            key=lambda e: e.finished_at, default=None,
        )
        if last_ex is not None:
            return await check_operator_access(
                db, user.id, last_ex.node_id, batch.route_id,
                node_stage_names.get(last_ex.node_id), batch=batch,
            )
        # 无已完成执行：退回归属判定（require_batch_owner_access 同口径）
        return batch.owner_user_id is None or batch.owner_user_id == user.id

    eq_by_exec: dict[uuid.UUID, list[EquipmentSnapshotOut]] = {}
    for eq in equipments:
        eq_by_exec.setdefault(eq.execution_id, []).append(
            EquipmentSnapshotOut.model_validate(eq)
        )
    val_by_exec: dict[uuid.UUID, list[FieldValueOut]] = {}
    for v in values:
        val_by_exec.setdefault(v.execution_id, []).append(
            FieldValueOut.model_validate(v)
        )
    missing_by_exec = await compute_missing_required_fields(db, executions)
    exec_outs = []
    for e in executions:
        out = ExecutionOut.model_validate(e)
        out.node_name = node_names.get(e.node_id)
        out.equipments = eq_by_exec.get(e.id, [])
        out.field_values = val_by_exec.get(e.id, [])
        out.missing_required_fields = missing_by_exec.get(e.id, [])
        out.can_backfill = await _can_backfill(e)
        exec_outs.append(out)
    detail = BatchDetailOut.model_validate(batch)
    detail.executions = exec_outs
    detail.can_complete = await _can_complete()
    # 填充路线名称
    route = await repo.get_route(db, batch.route_id)
    if route:
        detail.route_name = route.route_name
    # 计算字段汇总区
    detail.computed_fields = await expand_computed_fields(db, batch)
    return detail


async def list_batches_paged(
    db: AsyncSession,
    product_id: uuid.UUID | None,
    status: str | None,
    keyword: str | None,
    entry_node_filter: str | None = None,
    route_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
) -> tuple[list[Batch], int]:
    batches, total = await repo.list_batches(
        db, product_id, status, keyword, entry_node_filter, route_id, page, page_size, order_by, order
    )
    # 批量填充路线名称
    route_ids = list({b.route_id for b in batches})
    if route_ids:
        routes = await repo.get_routes_by_ids(db, route_ids)
        route_map = {r.id: r.route_name for r in routes}
        for b in batches:
            b.route_name = route_map.get(b.route_id, "")  # type: ignore[attr-defined]
    return batches, total
