"""用户职责范围查询 — 查询用户负责的工序和进行中的批次。"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastmcp.tools.base import ToolResult
from sqlalchemy import select

from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import (
    _BATCH_STATUS_CN,
    _SHANGHAI_TZ,
    _STATUS_MARK,
    _get_user_permitted_nodes,
    _get_user_permitted_nodes_xor,
    _scope_nodes,
)
from app.modules.production.models import Batch, NodeExecution, RouteNode
from app.modules.production.repository.assignment import get_user_node_assignments
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


@mcp.tool()
async def query_user_processes(operator_id: str) -> ToolResult:
    """查询指定用户目前负责哪些产品、哪些工艺路线上的哪些工序。

    基于工段负责人（StageAssignment）和工序负责人（NodeAssignment）配置。
    适用于 Agent 帮一线工人确认自己的职责范围。

    Args:
        operator_id: 用户的飞书 user_id 或姓名
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    permitted = await _get_user_permitted_nodes(db, user.id)

    if not permitted:
        return ToolResult(
            content=f"用户 **{user.name}** 目前没有负责任何工序。",
        )

    route_ids = list(permitted.keys())
    routes = await repo.get_routes_by_ids(db, route_ids)

    product_ids = list({r.product_id for r in routes})
    products = await repo.get_products_by_ids(db, product_ids)

    # 按 产品 → 路线 → 工段 → 工序 组织
    lines = [f"## {user.name} 负责的工序\n"]

    for product in sorted(products, key=lambda p: p.product_name):
        lines.append(f"### {product.product_name}")
        if product.product_code:
            lines.append(f"编码：{product.product_code}")
        lines.append("")

        product_routes = [r for r in routes if r.product_id == product.id]
        for route in sorted(product_routes, key=lambda r: r.route_name):
            lines.append(f"**{route.route_name}**（{route.status}）\n")

            all_route_nodes = await repo.get_route_nodes(db, route.id)
            route_permitted = permitted.get(route.id, set())
            route_nodes = [n for n in all_route_nodes if n.id in route_permitted]

            by_stage: dict[str, list[RouteNode]] = defaultdict(list)
            for node in route_nodes:
                stage = node.stage_name or "未分组"
                by_stage[stage].append(node)

            for stage in sorted(by_stage):
                nodes = sorted(by_stage[stage], key=lambda n: n.sort_order)
                lines.append(f"**{stage}**：")
                for node in nodes:
                    lines.append(f"  - {node.name}（`{node.node_code}`）")
                lines.append("")

    content = "\n".join(lines)
    return ToolResult(content=content)


@mcp.tool()
async def query_user_active_batches(operator_id: str, view_all: bool = False) -> ToolResult:
    """查询指定用户负责的工序中，哪些批次正在进行中。

    返回用户负责的工序所在的活跃批次（pending / in_progress），
    以及每个批次当前在哪个工序上。仅返回包含用户负责工序的批次。
    默认按批次归属过滤（无主共享 + 归属自己的可见），且归属他人的批次
    在用户有工序级分配（NodeAssignment）且对应工序待开始/进行中时也可见；
    view_all=True 时返回全部并标注归属人。

    Args:
        operator_id: 用户的飞书 user_id 或姓名
        view_all: 是否查看全部批次（默认 False，按归属过滤）
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    # XOR 权限模型（与工作台 query_workbench 一致）
    permitted = await _get_user_permitted_nodes_xor(db, user.id)

    if not permitted:
        return ToolResult(
            content=f"用户 **{user.name}** 目前没有负责任何工序，无进行中批次。",
        )

    route_ids = list(permitted.keys())

    # 查找活跃批次
    batch_stmt = (
        select(Batch)
        .where(
            Batch.route_id.in_(route_ids),
            Batch.status.in_(["pending", "in_progress"]),
            Batch.is_deleted == False,  # noqa: E712
        )
        .order_by(Batch.created_at.desc())
    )
    batches = list((await db.execute(batch_stmt)).scalars())

    if not batches:
        return ToolResult(
            content=f"用户 **{user.name}** 负责的工序暂无活跃批次。",
        )

    # 批量加载
    product_ids = list({b.product_id for b in batches})
    products = await repo.get_products_by_ids(db, product_ids)
    product_map = {p.id: p for p in products}

    route_ids_set = list({b.route_id for b in batches})
    routes = await repo.get_routes_by_ids(db, route_ids_set)
    route_map = {r.id: r for r in routes}

    # 批量加载节点和执行
    nodes_cache: dict[uuid.UUID, list[RouteNode]] = {}
    # 工序级分配（NodeAssignment）：归属他人批次可见性判断的豁免依据，
    # 惰性加载——view_all 或无需豁免时不查询
    node_assigned: dict[uuid.UUID, set[uuid.UUID]] | None = None
    exec_cache: dict[uuid.UUID, list[NodeExecution]] = {}

    lines = [f"## {user.name} 负责的进行中批次\n"]
    count = 0

    for batch in batches:
        if batch.route_id not in nodes_cache:
            nodes_cache[batch.route_id] = await repo.get_route_nodes(db, batch.route_id)
        if batch.id not in exec_cache:
            exec_cache[batch.id] = await repo.list_executions(db, batch.id)

        nodes = nodes_cache[batch.route_id]
        executions = exec_cache[batch.id]
        permitted_set = permitted.get(batch.route_id, set())

        # 构建每节点最新执行快照
        latest: dict[uuid.UUID, NodeExecution] = {}
        for ex in executions:
            cur = latest.get(ex.node_id)
            if cur is None or ex.execution_seq > cur.execution_seq:
                latest[ex.node_id] = ex

        # 确定本批次的工序范围：派生批次仅包含 entry_node 及之后的节点
        scope_nodes = _scope_nodes(nodes, batch.entry_node_id)

        # 归属过滤：归属他人的批次，仅当用户有工序级分配（NodeAssignment）
        # 且对应工序待开始/进行中时可见——工序负责人跨归属获取数据；
        # 工段级负责人（StageAssignment）保持归属隔离。view_all 时全量返回并标注归属人。
        if not view_all and batch.owner_user_id is not None and batch.owner_user_id != user.id:
            if node_assigned is None:
                node_assigned = defaultdict(set)
                for na in await get_user_node_assignments(db, user.id):
                    node_assigned[na.route_id].add(na.node_id)
            na_nodes = node_assigned.get(batch.route_id, set())
            if not any(
                n.id in na_nodes
                and (latest.get(n.id) is None or latest[n.id].status == "in_progress")
                for n in scope_nodes
            ):
                continue

        # 筛选用户在本次批次范围内负责的节点（按 sort_order 排序）
        my_nodes = sorted(
            [n for n in scope_nodes if n.id in permitted_set],
            key=lambda n: n.sort_order,
        )
        if not my_nodes:
            continue

        # 判断是否相关：负责的节点中有 in_progress 或尚未开始
        has_in_progress = any(
            latest.get(n.id) and latest[n.id].status == "in_progress"
            for n in my_nodes
        )
        has_pending = any(
            latest.get(n.id) is None for n in my_nodes
        )
        if not has_in_progress and not has_pending:
            continue

        count += 1

        # --- 构建批次输出 ---
        product = product_map.get(batch.product_id)
        route = route_map.get(batch.route_id)

        lines.append(f"### {batch.batch_no}")
        quantity = batch.quantity if batch.quantity is not None else "—"
        owner_hint = f" | 归属：{batch.owner_name}" if batch.owner_name else ""
        lines.append(f"- 产品：{product.product_name if product else '—'} | 路线：{route.route_name if route else '—'} | 状态：{_BATCH_STATUS_CN.get(batch.status, batch.status)} | 数量：{quantity} {batch.unit or ''}{owner_hint}")

        # 进度概览（仅统计用户负责的工序，与表格一致）
        total_count = len(my_nodes)
        completed_count = sum(
            1 for n in my_nodes if latest.get(n.id) and latest[n.id].status == "completed"
        )
        in_progress_nodes = [
            n for n in my_nodes
            if latest.get(n.id) and latest[n.id].status == "in_progress"
        ]
        if in_progress_nodes:
            ip = in_progress_nodes[0]
            stage_hint = f" [{ip.stage_name}]" if ip.stage_name else ""
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 已完成，当前进行中：{ip.name}{stage_hint}")
        elif completed_count == total_count:
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 全部完成")
        else:
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 已完成")

        # 仅列出用户负责的工序
        lines.append("")
        lines.append("你的负责工序：")
        lines.append("| 状态 | 工序 | 工段 | 详情 |")
        lines.append("|------|------|------|------|")
        for node in my_nodes:
            entry = latest.get(node.id)
            status = entry.status if entry else None
            mark = _STATUS_MARK.get(status, "[待开始]")
            stage = node.stage_name or "—"

            detail_parts = []
            if entry:
                detail_parts.append(f"第{entry.execution_seq}次")
                detail_parts.append(entry.started_at.astimezone(_SHANGHAI_TZ).strftime("%m-%d %H:%M"))
                if entry.finished_at:
                    detail_parts.append(f"-> {entry.finished_at.astimezone(_SHANGHAI_TZ).strftime('%m-%d %H:%M')}")
                if entry.owner_name:
                    detail_parts.append(entry.owner_name)
            detail = " · ".join(detail_parts) if detail_parts else "—"

            lines.append(f"| {mark} | {node.name} | {stage} | {detail} |")
        lines.append("")

    if count == 0:
        return ToolResult(
            content=f"用户 **{user.name}** 负责的工序暂无进行中的批次。",
        )

    lines.append(f"---\n共 **{count}** 个批次。")
    return ToolResult(content="\n".join(lines))
