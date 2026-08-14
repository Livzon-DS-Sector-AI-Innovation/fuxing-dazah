"""批次生命周期、derive/merge 谱系写入。谱系一致性只在本文件维护。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import Batch, BatchLink
from app.modules.production.schemas import (
    BatchCreate,
    BatchDetailOut,
    DeriveIn,
    EquipmentSnapshotOut,
    ExecutionOut,
    FieldValueOut,
    MergeIn,
)
from app.modules.production.service.assignment_service import (
    require_batch_owner_access,
    require_stage_permission,
)
from app.modules.production.service.execution_service import (
    compute_missing_required_fields,
)
from app.modules.production.service.planning_service import sync_plan_item_status
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User
from app.platform.permission.deps import get_user_permissions


async def _check_boundary_stage_permission(
    db: AsyncSession,
    user: User,
    edge_id: uuid.UUID,
    route_id: uuid.UUID,
) -> None:
    """校验用户对边界边起点工段的操作权限。

    边界边的 from_node 即父批次最后完成的工序节点，
    只有该工段或该节点的负责人才能从此边界派生/合并子批次。
    使用 repository 层查询而非原始 select，保持架构一致性。
    """
    edge = await repo.get_edge(db, edge_id)
    if not edge:
        return
    nodes = await repo.get_nodes_by_ids(db, [edge.from_node_id])
    from_node = nodes[0] if nodes else None
    if from_node and from_node.stage_name:
        await require_stage_permission(
            db, user.id, from_node.id, route_id, from_node.stage_name,
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
    if await repo.get_batch_by_no(db, payload.batch_no):
        raise DuplicateException("批号", payload.batch_no)
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
                await require_stage_permission(
                    db, user.id, last_ex.node_id, batch.route_id,
                    node.stage_name if node else None,
                )
            await require_batch_owner_access(user.id, batch)
            # stage_name 为 None 时 require_stage_permission 自行处理

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


async def get_batch_detail(db: AsyncSession, batch_id: uuid.UUID) -> BatchDetailOut:
    """批次详情 = 批次 + 执行时间线（含设备快照、字段值、工序名）。"""
    batch = await _get_batch_or_404(db, batch_id)
    executions = await repo.list_executions(db, batch_id)
    exec_ids = [e.id for e in executions]
    equipments = await repo.get_equipments_by_executions(db, exec_ids)
    values = await repo.get_field_values_by_executions(db, exec_ids)
    nodes = await repo.get_nodes_by_ids(db, list({e.node_id for e in executions}))
    node_names = {n.id: n.name for n in nodes}

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
        exec_outs.append(out)
    detail = BatchDetailOut.model_validate(batch)
    detail.executions = exec_outs
    # 填充路线名称
    route = await repo.get_route(db, batch.route_id)
    if route:
        detail.route_name = route.route_name
    return detail


async def list_batches_paged(
    db: AsyncSession,
    product_id: uuid.UUID | None,
    status: str | None,
    keyword: str | None,
    entry_node_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
) -> tuple[list[Batch], int]:
    batches, total = await repo.list_batches(
        db, product_id, status, keyword, entry_node_filter, page, page_size, order_by, order
    )
    # 批量填充路线名称
    route_ids = list({b.route_id for b in batches})
    if route_ids:
        routes = await repo.get_routes_by_ids(db, route_ids)
        route_map = {r.id: r.route_name for r in routes}
        for b in batches:
            b.route_name = route_map.get(b.route_id, "")  # type: ignore[attr-defined]
    return batches, total
