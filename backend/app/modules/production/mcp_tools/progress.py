"""批次进度查询 — 查询批次当前进行到哪个工序。"""

from __future__ import annotations

import uuid

from fastmcp.tools.base import ToolResult

from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import (
    _BATCH_STATUS_CN,
    _SHANGHAI_TZ,
    _scope_nodes,
)
from app.modules.production.models import NodeExecution
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


@mcp.tool()
async def query_batch_progress(batch_no: str) -> ToolResult:
    """查询指定批次号当前进行到哪个工序。

    返回每个工序的状态（待开始 / 进行中 / 已完成 / 已中止），
    以及批次整体的进度概览和当前正在哪个工序上。

    Args:
        batch_no: 批次号
    """
    db = get_db()
    batch = await repo.get_batch_by_no(db, batch_no)
    if not batch:
        return ToolResult(content=f"未找到批次：{batch_no}")

    nodes = await repo.get_route_nodes(db, batch.route_id)
    executions = await repo.list_executions(db, batch.id)
    product = await repo.get_product(db, batch.product_id)
    route = await repo.get_route(db, batch.route_id)

    # 派生批次只看 entry_node 及之后的工序
    entry_node = next((n for n in nodes if n.id == batch.entry_node_id), None) if batch.entry_node_id else None
    scope_nodes = _scope_nodes(
        nodes, batch.entry_node_id,
        entry_node.sort_order if entry_node else None,
    )

    # 每节点最新执行
    latest: dict[uuid.UUID, NodeExecution] = {}
    for ex in executions:
        cur = latest.get(ex.node_id)
        if cur is None or ex.execution_seq > cur.execution_seq:
            latest[ex.node_id] = ex

    # 仅在范围内的节点中统计（集合预构建，避免在推导式过滤条件中重复计算）
    scope_node_ids = {n.id for n in scope_nodes}
    scope_latest = {nid: ex for nid, ex in latest.items() if nid in scope_node_ids}
    completed_nodes = [
        n for n in scope_nodes
        if scope_latest.get(n.id) and scope_latest[n.id].status == "completed"
    ]
    in_progress_node = next(
        (n for n in scope_nodes
         if scope_latest.get(n.id) and scope_latest[n.id].status == "in_progress"),
        None,
    )

    status_cn = _BATCH_STATUS_CN.get(batch.status, batch.status)
    quantity = batch.quantity if batch.quantity is not None else "—"
    lines = [
        f"## 批次 {batch_no} 进度",
        "",
        f"- 产品：{product.product_name if product else '—'}",
        f"- 路线：{route.route_name if route else '—'}",
        f"- 状态：{status_cn}",
        f"- 数量：{quantity} {batch.unit or ''}",
    ]

    if in_progress_node:
        ex = scope_latest[in_progress_node.id]
        stage_hint = f" [{in_progress_node.stage_name}]" if in_progress_node.stage_name else ""
        started = ex.started_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")
        lines.append(f"- 当前工序：{in_progress_node.name}{stage_hint} — 进行中，第{ex.execution_seq}次，开始 {started}，负责人 {ex.owner_name or '—'}")
    elif completed_nodes:
        last = completed_nodes[-1]
        ex = scope_latest[last.id]
        finished = ex.finished_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M") if ex.finished_at else "—"
        started = ex.started_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")
        stage_hint = f" [{last.stage_name}]" if last.stage_name else ""
        lines.append(f"- 最后完成工序：{last.name}{stage_hint} — 已完成，第{ex.execution_seq}次，{started} -> {finished}，负责人 {ex.owner_name or '—'}")
    else:
        # 尚未开始任何工序
        if scope_nodes:
            first = scope_nodes[0]
            lines.append(f"- 下一工序：{first.name} [{first.stage_name or '—'}] — 等待开始")

    if completed_nodes:
        names = "、".join(n.name for n in completed_nodes)
        lines.append(f"- 已完成工序：{len(completed_nodes)} 道（{names}）")

    if batch.entry_node_id and entry_node:
        lines.append(f"- 入口节点：{entry_node.name}（派生批次，此前工序属父批次）")

    return ToolResult(content="\n".join(lines))
