"""工作台待办查询与接收并开始。"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production import repository as repo
from app.modules.production.models import Batch, BatchLink, NodeExecution
from app.modules.production.models.planning import PlanAllocation
from app.modules.production.models.route import RouteNode
from app.modules.production.schemas.assignment import (
    AssignedNodeInfo,
    AssignedRouteInfo,
    AssignedStageInfo,
    NodeAssigneeInfo,
    PlannedBatchItem,
    PlannedBatchOut,
    ReceiveAndStartIn,
    RecentCompletedItem,
    StageNodeInfo,
    WorkbenchItem,
    WorkbenchOut,
)
from app.modules.production.schemas.batch import DeriveIn, MergeIn, MergeParentIn
from app.modules.production.service.batch_service import derive_batches, merge_batches
from app.modules.production.service.execution_service import start_execution
from app.platform.identity.models import User


async def _get_user_names(
    db: AsyncSession, user_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """批量查用户名。"""
    if not user_ids:
        return {}
    stmt = select(User).where(
        User.id.in_(list(user_ids)),
        User.is_deleted == False,  # noqa: E712
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {u.id: u.name for u in rows}


def _build_assignee_info(assignments) -> list[NodeAssigneeInfo]:
    """将 NodeAssignment 列表转为 NodeAssigneeInfo。"""
    return [NodeAssigneeInfo(user_id=a.user_id) for a in assignments]


def _build_stage_nodes(
    stage_nodes: list[RouteNode],
    completed: set[uuid.UUID],
    in_progress: set[uuid.UUID],
) -> list[StageNodeInfo]:
    """构建工序面包屑：预排序的工段内工序，标记完成状态。ponytail: 调用方预分组，避免重复过滤排序。"""
    if not stage_nodes:
        return []
    result: list[StageNodeInfo] = []
    for n in stage_nodes:
        if n.id in completed:
            status = "completed"
        elif n.id in in_progress:
            status = "in_progress"
        else:
            status = "pending"
        result.append(StageNodeInfo(
            node_id=n.id,
            node_name=n.name,
            sort_order=n.sort_order,
            status=status,
        ))
    return result


# ── 计划批次辅助 ──


def _build_stage_order(nodes: list[RouteNode]) -> list[str]:
    """从路线节点提取有序工段列表（按 sort_order 首次出现顺序）。"""
    seen: dict[str, int] = {}
    for n in sorted(nodes, key=lambda n: n.sort_order):
        sn = n.stage_name or "未分组"
        if sn not in seen:
            seen[sn] = n.sort_order
    return sorted(seen.keys(), key=lambda s: seen[s])


def _calc_stage_times(
    planned_start: datetime | None,
    stage_durations: list | None,
    stage_order: list[str],
) -> dict[str, str]:
    """计算每工段预计开始时间 = planned_start + 前序工段时长累加。

    stage_durations 为空时全部回退到 planned_start。
    """
    if not planned_start:
        return {}
    durations: dict[str, float] = {}
    if stage_durations:
        for d in stage_durations:
            durations[d.get("stage_name", "")] = d.get("duration_hours", 0)
    result: dict[str, str] = {}
    accumulated = timedelta(0)
    for sn in stage_order:
        result[sn] = (planned_start + accumulated).isoformat()
        if stage_durations:
            accumulated += timedelta(hours=durations.get(sn, 0))
    return result


def _calc_current_progress(
    stage_order: list[str],
    stage_node_ids: dict[str, set[uuid.UUID]],
    completed: set[uuid.UUID],
    in_progress: set[uuid.UUID],
) -> tuple[str | None, str | None]:
    """判断批次当前在哪个工段及进度状态。

    Returns (current_stage, progress): progress ∈ {not_started, in_progress, completed}
    """
    for sn in stage_order:
        sn_ids = stage_node_ids.get(sn, set())
        if not sn_ids:
            continue
        if sn_ids & in_progress:
            return sn, "in_progress"
        if not sn_ids.issubset(completed):
            return sn, "not_started"
    # 全部工段完成 — 但空路由无任何工段，不应标记为 completed
    if not stage_order:
        return None, None
    return stage_order[-1], "completed"


# ── 计划批次查询 ──


async def activate_planned_batch(
    db: AsyncSession, batch_id: uuid.UUID, user: User,
) -> Batch:
    """激活计划批次：scheduled → pending，第一工段负责人接收后进入待办区。"""
    batch = await repo.get_batch(db, batch_id)
    if not batch:
        raise AppException(status_code=404, message=f"批次 {batch_id} 不存在")
    if batch.status != "scheduled":
        raise AppException(status_code=400, message="仅 scheduled 批次可激活")
    if batch.creation_type != "plan":
        raise AppException(status_code=400, message="仅计划批次可激活")

    # verify user owns the first stage of this batch's route
    user_stages = await repo.get_user_stages(db, user.id)
    user_route_stages = {
        s.stage_name for s in user_stages if s.route_id == batch.route_id
    }
    if not user_route_stages:
        raise AppException(status_code=403, message="您无权激活此批次")
    nodes = await repo.get_route_nodes(db, batch.route_id)
    stage_order = _build_stage_order(nodes)
    if not stage_order or stage_order[0] not in user_route_stages:
        raise AppException(status_code=403, message="仅路线第一工段负责人可激活批次")

    batch.status = "pending"
    batch.updated_by = user.id if user else None
    await db.flush()
    # re-fetch per SQLAlchemy async rule: UPDATE flush doesn't use RETURNING
    refreshed = await repo.get_batch(db, batch_id)
    assert refreshed is not None
    return refreshed


async def query_planned_batches(
    db: AsyncSession, user_id: uuid.UUID,
) -> PlannedBatchOut:
    """查询用户负责工段对应的计划批次排期。

    只返回 scheduled + creation_type=plan 的批次。
    每个工段负责人看到自己工段的预计开始时间。
    """
    stages = await repo.get_user_stages(db, user_id)
    if not stages:
        return PlannedBatchOut(items=[])

    # per-route stage name mapping: avoid cross-route name collision (e.g. "清洗" on Route-A vs Route-B)
    route_stage_names: dict[uuid.UUID, set[str]] = defaultdict(set)
    for s in stages:
        route_stage_names[s.route_id].add(s.stage_name)
    route_ids = list({s.route_id for s in stages})

    routes = await repo.get_routes_by_ids(db, route_ids)
    routes = [r for r in routes if r.status == "published"]
    if not routes:
        return PlannedBatchOut(items=[])
    route_map = {r.id: r for r in routes}
    published_route_ids = set(route_map.keys())

    product_ids = {r.product_id for r in routes}
    products = await repo.get_products_by_ids(db, list(product_ids))
    product_map = {p.id: p for p in products}

    # 查 scheduled plan 批次
    batch_stmt = select(Batch).where(
        Batch.route_id.in_(list(published_route_ids)),
        Batch.status == "scheduled",
        Batch.creation_type == "plan",
        Batch.is_deleted == False,  # noqa: E712
    )
    scheduled_batches: list[Batch] = list((await db.execute(batch_stmt)).scalars())
    if not scheduled_batches:
        return PlannedBatchOut(items=[])

    batch_map = {b.id: b for b in scheduled_batches}

    # PlanAllocation → PlanItem → PlanOrder
    allocs = await repo.get_plan_allocations_by_batches(db, list(batch_map.keys()))
    alloc_by_batch: dict[uuid.UUID, PlanAllocation] = {}
    item_ids: set[uuid.UUID] = set()
    for a in allocs:
        alloc_by_batch[a.batch_id] = a
        item_ids.add(a.plan_item_id)

    items = await repo.get_plan_items_by_ids(db, list(item_ids))
    item_map = {i.id: i for i in items}

    order_ids = {i.plan_order_id for i in items}
    order_map = await repo.get_plan_orders_by_ids(db, list(order_ids))

    # 路线节点缓存 + 每路线预计算 stage_order / stage_node_ids
    route_stage_order: dict[uuid.UUID, list[str]] = {}
    route_stage_node_ids: dict[uuid.UUID, dict[str, set[uuid.UUID]]] = {}
    for rid in published_route_ids:
        nodes = await repo.get_route_nodes(db, rid)
        stage_order = _build_stage_order(nodes)
        route_stage_order[rid] = stage_order
        route_stage_node_ids[rid] = {
            sn: {n.id for n in nodes if (n.stage_name or "未分组") == sn}
            for sn in stage_order
        }

    # 批次执行状态 — 一次查询（ponytail: merged completed + in_progress）
    all_batch_ids = list(batch_map.keys())
    batch_completed: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    batch_in_progress: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if all_batch_ids:
        for row in (await db.execute(
            select(NodeExecution.batch_id, NodeExecution.node_id, NodeExecution.status).where(
                NodeExecution.batch_id.in_(all_batch_ids),
                NodeExecution.status.in_(["completed", "in_progress"]),
                NodeExecution.is_deleted == False,  # noqa: E712
            )
        )).all():
            if row.status == "completed":
                batch_completed[row.batch_id].add(row.node_id)
            else:
                batch_in_progress[row.batch_id].add(row.node_id)

    now = datetime.now(UTC)

    result: list[PlannedBatchItem] = []
    for batch in scheduled_batches:
        alloc = alloc_by_batch.get(batch.id)
        if not alloc:
            continue
        item = item_map.get(alloc.plan_item_id)
        if not item:
            continue
        order = order_map.get(item.plan_order_id)

        route = route_map[batch.route_id]
        product = product_map.get(route.product_id)

        stage_order = route_stage_order[batch.route_id]
        user_stages = [s for s in stage_order if s in route_stage_names.get(batch.route_id, set())]
        if not user_stages:
            continue

        stage_times = _calc_stage_times(item.planned_start, item.stage_durations, stage_order)
        completed = batch_completed.get(batch.id, set())
        in_progress = batch_in_progress.get(batch.id, set())
        stage_node_ids = route_stage_node_ids[batch.route_id]
        current_stage, current_progress = _calc_current_progress(
            stage_order, stage_node_ids, completed, in_progress,
        )

        # 时间过滤：±30天
        if item.planned_start:
            one_month = timedelta(days=30)
            if item.planned_start > now + one_month:
                continue
            if item.planned_end and item.planned_end < now - one_month:
                continue

        # 标记该用户是否为第一工段负责人
        first_user_stage = user_stages[0]
        is_first_stage_owner = (first_user_stage == stage_order[0])

        # 如果当前执行进度已超过该用户的所有工段 → 不显示
        if current_stage and current_stage not in user_stages:
            if stage_order.index(current_stage) > max(stage_order.index(us) for us in user_stages):
                continue

        result.append(PlannedBatchItem(
            batch_id=batch.id,
            batch_no=batch.batch_no,
            product_name=product.product_name if product else None,
            route_id=route.id,
            route_name=route.route_name,
            plan_item_id=item.id,
            plan_order_no=order.order_no if order else "",
            planned_start=item.planned_start.isoformat() if item.planned_start else None,
            planned_end=item.planned_end.isoformat() if item.planned_end else None,
            stage_times=stage_times,
            current_stage=current_stage,
            current_stage_progress=current_progress,
            stage_config=item.stage_durations or (order.stage_config if order else None),
            is_first_stage_owner=is_first_stage_owner,
        ))

    result.sort(key=lambda x: x.planned_start or "")
    return PlannedBatchOut(items=result)


async def query_workbench(
    db: AsyncSession, user_id: uuid.UUID,
) -> WorkbenchOut:
    """工作台待办查询：pending_start + pending_receive。"""
    stages = await repo.get_user_stages(db, user_id)
    node_assignments = await repo.get_user_node_assignments(db, user_id)

    role = "stage_owner" if stages else "node_owner"
    stage_names = list({s.stage_name for s in stages})

    # 用户权限：路线 → 工段/节点
    route_stages: dict[uuid.UUID, set[str]] = defaultdict(set)
    route_nodes: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for s in stages:
        route_stages[s.route_id].add(s.stage_name)
    for na in node_assignments:
        route_nodes[na.route_id].add(na.node_id)

    all_route_ids = set(route_stages) | set(route_nodes)
    if not all_route_ids:
        return WorkbenchOut(role=role, stage_names=stage_names, assigned_routes=[], items=[])

    routes = await repo.get_routes_by_ids(db, list(all_route_ids))
    # 只保留已发布的路线（排除草稿和已归档）
    routes = [r for r in routes if r.status == "published"]
    route_map = {r.id: r for r in routes}
    product_ids = {r.product_id for r in routes}
    products = await repo.get_products_by_ids(db, list(product_ids))
    product_map = {p.id: p for p in products}

    # 缓存所有路线的节点和边（避免每路线重复查询）
    route_nodes_cache: dict[uuid.UUID, list] = {}
    route_edges_cache: dict[uuid.UUID, list] = {}
    for rid in route_map:
        route_nodes_cache[rid] = await repo.get_route_nodes(db, rid)
        route_edges_cache[rid] = await repo.get_route_edges(db, rid)

    # 构建 assigned_routes — 用户负责的路线/工段/节点结构
    assigned_routes: list[AssignedRouteInfo] = []
    for route_id in sorted(all_route_ids):
        r = route_map.get(route_id)
        if not r:
            continue
        p = product_map.get(r.product_id)
        route_stages_set = route_stages.get(route_id, set())
        route_nodes_set = route_nodes.get(route_id, set())
        if not route_stages_set and not route_nodes_set:
            continue
        rt_nodes = route_nodes_cache[route_id]
        node_map_by_route = {n.id: n for n in rt_nodes}
        stages_info: list[AssignedStageInfo] = []
        for sn in sorted(route_stages_set):
            stage_nodes = [
                AssignedNodeInfo(node_id=n.id, node_name=n.name)
                for n in rt_nodes if n.stage_name == sn
            ]
            stages_info.append(AssignedStageInfo(stage_name=sn, nodes=stage_nodes))
        # 直接分配的节点（不属于任何 stage 或用户只有节点分配）
        direct_nodes = [
            AssignedNodeInfo(node_id=nid, node_name=node_map_by_route[nid].name)
            for nid in sorted(route_nodes_set)
            if nid in node_map_by_route
        ]
        if direct_nodes and not stages_info:
            stages_info.append(AssignedStageInfo(stage_name="直接分配", nodes=direct_nodes))
        assigned_routes.append(AssignedRouteInfo(
            route_id=route_id,
            route_name=r.route_name,
            product_name=p.product_name if p else None,
            stages=stages_info,
        ))

    # ── 批量查询：所有路线的活跃/已完成批次、节点状态、已派生链接 ──
    active_by_route: dict[uuid.UUID, list[Batch]] = defaultdict(list)
    completed_by_route: dict[uuid.UUID, list[Batch]] = defaultdict(list)
    batch_stmt = select(Batch).where(
        Batch.route_id.in_(list(all_route_ids)),
        Batch.status.in_(("pending", "in_progress", "completed")),
        Batch.is_deleted == False,  # noqa: E712
    )
    for b in (await db.execute(batch_stmt)).scalars():
        if b.status == "completed":
            completed_by_route[b.route_id].append(b)
        else:
            active_by_route[b.route_id].append(b)

    all_active_ids = [b.id for lst in active_by_route.values() for b in lst]
    all_batch_ids_for_status = all_active_ids + [
        b.id for lst in completed_by_route.values() for b in lst
    ]
    batch_completed: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    batch_in_progress: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if all_batch_ids_for_status:
        for row in (
            await db.execute(
                select(NodeExecution.batch_id, NodeExecution.node_id, NodeExecution.status).where(
                    NodeExecution.batch_id.in_(all_batch_ids_for_status),
                    NodeExecution.status.in_(["completed", "in_progress"]),
                    NodeExecution.is_deleted == False,  # noqa: E712
                )
            )
        ).all():
            if row.status == "completed":
                batch_completed[row.batch_id].add(row.node_id)
            else:
                batch_in_progress[row.batch_id].add(row.node_id)

    linked_pairs: set[tuple] = set()
    all_boundary_edge_ids = {
        e.id for rid in route_map for e in route_edges_cache[rid] if e.is_batch_boundary
    }
    if all_batch_ids_for_status and all_boundary_edge_ids:
        for row in (
            await db.execute(
                select(BatchLink.parent_batch_id, BatchLink.edge_id).where(
                    BatchLink.parent_batch_id.in_(all_batch_ids_for_status),
                    BatchLink.edge_id.in_(all_boundary_edge_ids),
                    BatchLink.is_deleted == False,  # noqa: E712
                )
            )
        ).all():
            linked_pairs.add((row.parent_batch_id, row.edge_id))

    # 批量查询进行中的执行记录——提到 route 循环外，避免每个路线一次 DB 查询
    in_progress_execs_by_batch: dict[uuid.UUID, list[NodeExecution]] = defaultdict(list)
    if all_active_ids:
        exec_stmt = select(NodeExecution).where(
            NodeExecution.status == "in_progress",
            NodeExecution.batch_id.in_(all_active_ids),
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        for ex in (await db.execute(exec_stmt)).scalars():
            in_progress_execs_by_batch[ex.batch_id].append(ex)

    items: list[WorkbenchItem] = []

    for route_id in sorted(all_route_ids):
        route = route_map.get(route_id)
        if not route:
            continue
        product_name = product_map.get(route.product_id)
        product_name = product_name.product_name if product_name else None

        nodes = route_nodes_cache[route_id]
        edges = route_edges_cache[route_id]
        node_map = {n.id: n for n in nodes}

        # 预分组：工段 → 已排序节点列表（ponytail: 避免 _build_stage_nodes 内重复过滤和排序）
        nodes_by_stage: dict[str, list[RouteNode]] = {}
        for n in nodes:
            sn = n.stage_name or "未分组"
            nodes_by_stage.setdefault(sn, []).append(n)
        for lst in nodes_by_stage.values():
            lst.sort(key=lambda n: n.sort_order)

        # 用户在此路线有权限的节点
        if role == "stage_owner":
            permitted_stages = route_stages.get(route_id, set())
            permitted_node_ids = {
                n.id for n in nodes if n.stage_name in permitted_stages
            }
        else:
            permitted_node_ids = route_nodes.get(route_id, set())

        if not permitted_node_ids:
            continue

        batches = active_by_route.get(route_id, [])
        if not batches:
            continue

        # 边索引
        edges_by_to: dict[uuid.UUID, list] = defaultdict(list)
        for e in edges:
            edges_by_to[e.to_node_id].append(e)

        # ── pending_start ──
        for b in batches:
            completed = batch_completed.get(b.id, set())
            in_progress = batch_in_progress.get(b.id, set())
            for node_id in permitted_node_ids:
                node = node_map.get(node_id)
                if not node:
                    continue
                if node_id in completed or node_id in in_progress:
                    continue
                # 衍生批次的 entry_node 无需前序条件 — 它从父批次继承了状态
                if b.entry_node_id and node_id == b.entry_node_id:
                    legal = True
                else:
                    incoming = edges_by_to.get(node_id, [])
                    if incoming:
                        legal = False
                        for e in incoming:
                            if e.from_node_id in completed and not e.is_batch_boundary:
                                legal = True
                                break
                            if (
                                e.allow_overlap
                                and not e.is_batch_boundary
                                and e.from_node_id in in_progress
                            ):
                                legal = True
                                break
                        if not legal:
                            continue
                    else:
                        # 无入边 = 起点；非 entry 批次只允许 entry_node
                        if b.entry_node_id and node_id != b.entry_node_id:
                            continue

                items.append(WorkbenchItem(
                    type="pending_start",
                    batch_id=b.id,
                    batch_no=b.batch_no,
                    product_name=product_name,
                    route_id=route_id,
                    route_name=route.route_name,
                    node_id=node_id,
                    node_name=node.name,
                    stage_name=node.stage_name,
                    predecessor_batches=[],
                    node_assignees=[],
                    stage_nodes=_build_stage_nodes(nodes_by_stage.get(node.stage_name or "未分组", []), completed, in_progress),
                ))

        # ── pending_receive ──
        route_completed = completed_by_route.get(route_id, [])
        all_receive_batches = list(batches) + route_completed

        boundary_by_to: dict[uuid.UUID, list[tuple]] = defaultdict(list)
        for e in edges:
            if not e.is_batch_boundary:
                continue
            if e.to_node_id not in permitted_node_ids:
                continue
            for b in all_receive_batches:
                if e.from_node_id not in batch_completed.get(b.id, set()):
                    continue
                if (b.id, e.id) in linked_pairs:
                    continue
                boundary_by_to[e.to_node_id].append((e, b))

        for to_node_id, pairs in boundary_by_to.items():
            node = node_map.get(to_node_id)
            if not node:
                continue

            # 指向此 to_node 的边界边数量：1 = 分裂，>1 = 合并
            boundary_edge_ids = {
                e.id for e in edges
                if e.is_batch_boundary and e.to_node_id == to_node_id
            }
            is_merge = len(boundary_edge_ids) > 1

            if is_merge:
                parent_ids = list({b.id for _, b in pairs})
                parent_nos = [b.batch_no for _, b in pairs]
                # 合并接收无单一 batch_id，面包屑全显示 pending
                items.append(WorkbenchItem(
                    type="pending_receive",
                    route_id=route_id,
                    route_name=route.route_name,
                    node_id=to_node_id,
                    node_name=node.name,
                    stage_name=node.stage_name,
                    product_name=product_name,
                    parent_batch_ids=parent_ids,
                    predecessor_batches=parent_nos,
                    node_assignees=[],
                    stage_nodes=_build_stage_nodes(nodes_by_stage.get(node.stage_name or "未分组", []), set(), set()),
                ))
            else:
                for edge, b in pairs:
                    batch_comp = batch_completed.get(b.id, set())
                    batch_ip = batch_in_progress.get(b.id, set())
                    items.append(WorkbenchItem(
                        type="pending_receive",
                        batch_id=b.id,
                        batch_no=b.batch_no,
                        route_id=route_id,
                        route_name=route.route_name,
                        node_id=to_node_id,
                        node_name=node.name,
                        stage_name=node.stage_name,
                        product_name=product_name,
                        boundary_edge_id=edge.id,
                        parent_batch_ids=[b.id],
                        predecessor_batches=[],
                        node_assignees=[],
                        stage_nodes=_build_stage_nodes(nodes_by_stage.get(node.stage_name or "未分组", []), batch_comp, batch_ip),
                    ))

        # ── pending_complete：用户权限节点上有进行中的执行 ──
        in_progress_execs = [
            ex for b in batches
            for ex in in_progress_execs_by_batch.get(b.id, [])
        ]
        for ex in in_progress_execs:
            if ex.node_id not in permitted_node_ids:
                continue
            node = node_map.get(ex.node_id)
            if not node:
                continue
            b = next((b for b in batches if b.id == ex.batch_id), None)
            if not b:
                continue
            # 检查是否是工段内最后一个节点
            is_last = True
            stage_nodes = {n.id for n in nodes if n.stage_name == node.stage_name}
            completed = batch_completed.get(b.id, set())
            in_progress = batch_in_progress.get(b.id, set())
            for sn_id in stage_nodes:
                if sn_id != node.id and sn_id not in completed and sn_id not in in_progress:
                    is_last = False
                    break
            items.append(WorkbenchItem(
                type="pending_complete",
                batch_id=b.id,
                batch_no=b.batch_no,
                product_name=product_name,
                route_id=route_id,
                route_name=route.route_name,
                node_id=node.id,
                node_name=node.name,
                stage_name=node.stage_name,
                execution_id=ex.id,
                execution_seq=ex.execution_seq,
                owner_name=ex.owner_name,
                started_at=ex.started_at.isoformat() if ex.started_at else None,
                is_last_in_stage=is_last,
                predecessor_batches=[],
                node_assignees=[],
                stage_nodes=_build_stage_nodes(nodes_by_stage.get(node.stage_name or "未分组", []), completed, in_progress),
            ))

        # ── ready_to_complete：工段内所有节点已完成且有批次边界出边 ──
        # 按工段分组，每组独立判断
        stage_names_in_permitted = {
            node_map[nid].stage_name for nid in permitted_node_ids
            if nid in node_map and node_map[nid].stage_name
        }
        for b in batches:
            if b.status != "in_progress":
                continue
            comp = batch_completed.get(b.id, set())
            ip = batch_in_progress.get(b.id, set())
            for stage_name in stage_names_in_permitted:
                stage_node_ids = {
                    nid for nid in permitted_node_ids
                    if nid in node_map and node_map[nid].stage_name == stage_name
                }
                if not stage_node_ids:
                    continue
                all_stage_done = all(nid in comp for nid in stage_node_ids)
                if not all_stage_done:
                    continue
                has_in_progress = any(nid in ip for nid in stage_node_ids)
                if has_in_progress:
                    continue
                # 检查此工段是否有批次边界出边，或者是路线终点
                has_boundary_out = any(
                    e.is_batch_boundary and e.from_node_id in stage_node_ids
                    for e in edges
                )
                is_route_end = not any(
                    e.from_node_id in stage_node_ids
                    for e in edges
                )
                if not has_boundary_out and not is_route_end:
                    continue
                last_node = next((node_map[nid] for nid in stage_node_ids if nid in node_map), None)
                if not last_node:
                    continue
                items.append(WorkbenchItem(
                    type="ready_to_complete",
                    batch_id=b.id, batch_no=b.batch_no,
                    product_name=product_name,
                    node_id=last_node.id, node_name=last_node.name,
                    stage_name=stage_name,
                    predecessor_batches=[],
                    node_assignees=[],
                    stage_nodes=_build_stage_nodes(nodes_by_stage.get(stage_name or "未分组", []), comp, ip),
                ))

    # 批量填充 predecessor_batches（替代 N+1 的 _get_predecessor_batch_nos 调用）
    item_batch_ids = {it.batch_id for it in items if it.batch_id}
    if item_batch_ids:
        pred_stmt = (
            select(BatchLink.child_batch_id, Batch.batch_no)
            .join(Batch, Batch.id == BatchLink.parent_batch_id)
            .where(
                BatchLink.child_batch_id.in_(item_batch_ids),
                BatchLink.is_deleted == False,  # noqa: E712
                Batch.is_deleted == False,  # noqa: E712
            )
        )
        pred_map: dict[uuid.UUID, list[str]] = defaultdict(list)
        for row in (await db.execute(pred_stmt)).all():
            pred_map[row.child_batch_id].append(row.batch_no)
        for item in items:
            if item.batch_id:
                item.predecessor_batches = pred_map.get(item.batch_id, [])

    # 填充 node_assignees + name（只取当前用户配置的默认值）
    all_node_ids = {it.node_id for it in items}
    assignments = await repo.get_node_assignments_by_nodes(db, list(all_node_ids))
    assign_by_node: dict[uuid.UUID, list] = defaultdict(list)
    assign_user_ids: set[uuid.UUID] = set()
    for a in assignments:
        if a.assigned_by != user_id:
            continue
        assign_by_node[a.node_id].append(a)
        assign_user_ids.add(a.user_id)

    user_names = await _get_user_names(db, assign_user_ids)

    for item in items:
        item.node_assignees = _build_assignee_info(assign_by_node.get(item.node_id, []))
        for a in item.node_assignees:
            a.name = user_names.get(a.user_id)

    # ── 最近30天完成的记录 ──
    recent: list[RecentCompletedItem] = []
    since = datetime.now(UTC) - timedelta(days=30)
    # 收集所有路线节点（使用已缓存的 route_nodes_cache）
    all_nodes: dict[uuid.UUID, tuple] = {}  # node_id -> (node, route)
    for rid in route_map:
        for n in route_nodes_cache[rid]:
            all_nodes[n.id] = (n, route_map[rid])
    recent_exec_stmt = select(NodeExecution).where(
        NodeExecution.status == "completed",
        NodeExecution.finished_at >= since,
        NodeExecution.batch_id.in_(
            select(Batch.id).where(
                Batch.route_id.in_(list(route_map.keys())),
                Batch.is_deleted == False,  # noqa: E712
            )
        ),
        NodeExecution.is_deleted == False,  # noqa: E712
    ).order_by(NodeExecution.finished_at.desc()).limit(50)
    recent_execs = list((await db.execute(recent_exec_stmt)).scalars())
    recent_batch_ids = {e.batch_id for e in recent_execs}
    if recent_batch_ids:
        b_stmt = select(Batch).where(Batch.id.in_(list(recent_batch_ids)))
        recent_batches_map = {b.id: b for b in (await db.execute(b_stmt)).scalars().all()}
    else:
        recent_batches_map = {}
    for ex in recent_execs:
        entry = all_nodes.get(ex.node_id)
        if not entry:
            continue
        node, route = entry
        # 权限过滤
        user_stages = route_stages.get(route.id, set())
        user_nodes = route_nodes.get(route.id, set())
        if node.stage_name not in user_stages and ex.node_id not in user_nodes:
            continue
        b = recent_batches_map.get(ex.batch_id)
        if not b:
            continue
        p = product_map.get(route.product_id)
        recent.append(RecentCompletedItem(
            batch_no=b.batch_no, batch_id=b.id,
            product_name=p.product_name if p else None,
            route_id=route.id, route_name=route.route_name,
            node_id=node.id, node_name=node.name,
            stage_name=node.stage_name,
            execution_id=ex.id,
            owner_name=ex.owner_name,
            finished_at=ex.finished_at.isoformat() if ex.finished_at else None,
        ))

    items.sort(key=lambda x: x.batch_no or "")
    return WorkbenchOut(
        role=role, stage_names=stage_names,
        assigned_routes=assigned_routes, items=items,
        recent_completed=recent,
    )


async def receive_and_start(
    db: AsyncSession,
    body: ReceiveAndStartIn,
    user: User,
) -> dict:
    """接收并可选开始：derive 或 merge，然后可立即开始执行。"""
    parent_count = len(body.parent_batch_ids)
    if parent_count == 0:
        from app.core.exceptions import AppException
        raise AppException(status_code=400, message="至少需要一个父批次")

    if parent_count == 1:
        if not body.children:
            from app.core.exceptions import AppException
            raise AppException(status_code=400, message="至少需要指定一个子批次")
        derive_in = DeriveIn(
            edge_id=body.edge_id,
            deviation_reason=body.deviation_reason,
            children=body.children,
        )
        children = await derive_batches(db, body.parent_batch_ids[0], derive_in, user)
    else:
        if not body.children:
            from app.core.exceptions import AppException
            raise AppException(status_code=400, message="合并需要指定子批次信息")
        first = body.children[0]
        # 均分子批次总量到各父批次
        allocated = first.quantity / parent_count if first.quantity else None
        parents_in = [MergeParentIn(batch_id=pid, allocated_qty=allocated) for pid in body.parent_batch_ids]
        merge_in = MergeIn(
            parents=parents_in,
            edge_id=body.edge_id,
            deviation_reason=body.deviation_reason,
            batch_no=first.batch_no,
            quantity=first.quantity,
            unit=first.unit,
        )
        children = [await merge_batches(db, merge_in, user)]

    result: dict = {
        "children": [
            {"id": str(c.id), "batch_no": c.batch_no, "status": c.status}
            for c in children
        ],
        "execution": None,
    }

    # ── 可选立即开始 ──
    if body.start_execution and body.execution and children:
        execution = await start_execution(db, children[0].id, body.execution, user)
        result["execution"] = {
            "id": str(execution.id),
            "node_id": str(execution.node_id),
            "status": execution.status,
        }

    return result
