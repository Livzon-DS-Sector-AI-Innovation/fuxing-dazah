"""批次全链路追溯 — 查询批次及其前序、后序批次的执行进度。"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastmcp.tools.base import ToolResult

from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import _BATCH_STATUS_CN
from app.modules.production.schemas.trace import TraceBatch, TraceExecutionBrief
from app.modules.production.service import trace_service
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


@mcp.tool()
async def query_batch_trace(batch_no: str) -> ToolResult:
    """查询一个批次及其所有前序、后序批次，并展示每个批次的工序执行进度。

    结果以 Markdown 输出，包含完整批次关系、当前执行工序和已完成工序。
    适用于追溯批次来源、去向，以及确认当前批次执行到哪个工序。

    Args:
        batch_no: 要查询的批次号
    """
    db = get_db()
    root_batch = await repo.get_batch_by_no(db, batch_no)
    if not root_batch:
        return ToolResult(content=f"未找到批次：{batch_no}")

    trace = await trace_service.get_trace(db, root_batch.id)
    batches_by_id = {batch.id: batch for batch in trace.batches}
    products = await repo.get_products_by_ids(
        db, list({batch.product_id for batch in trace.batches})
    )
    product_names = {product.id: product.product_name for product in products}

    parents_by_child: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    children_by_parent: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for link in trace.links:
        parents_by_child[link.child_batch_id].add(link.parent_batch_id)
        children_by_parent[link.parent_batch_id].add(link.child_batch_id)

    def collect_related(
        start_id: uuid.UUID, relation_map: dict[uuid.UUID, set[uuid.UUID]],
    ) -> set[uuid.UUID]:
        found: set[uuid.UUID] = set()
        pending = list(relation_map.get(start_id, set()))
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(relation_map.get(current, set()))
        return found

    ancestor_ids = collect_related(root_batch.id, parents_by_child)
    descendant_ids = collect_related(root_batch.id, children_by_parent)

    def describe_progress(trace_batch: TraceBatch) -> tuple[str, str]:
        latest_by_step: dict[str, TraceExecutionBrief] = {}
        for execution in trace_batch.executions:
            existing = latest_by_step.get(execution.node_name)
            if existing is None or execution.started_at > existing.started_at:
                latest_by_step[execution.node_name] = execution

        in_progress = sorted(
            (
                execution for execution in latest_by_step.values()
                if execution.status == "in_progress"
            ),
            key=lambda execution: execution.started_at,
        )
        completed = sorted(
            (
                execution for execution in latest_by_step.values()
                if execution.status == "completed"
            ),
            key=lambda execution: execution.finished_at or execution.started_at,
        )

        if in_progress:
            current = "、".join(
                f"{execution.node_name}（进行中，{execution.owner_name or '未指派'}）"
                for execution in in_progress
            )
        elif completed:
            last = completed[-1]
            current = f"{last.node_name}（最近完成）"
        else:
            current = "尚未开始"

        completed_names = "、".join(execution.node_name for execution in completed) or "—"
        return current, completed_names

    def relation_label(batch_id: uuid.UUID) -> str:
        if batch_id == root_batch.id:
            return "目标批次"
        if batch_id in ancestor_ids:
            return "前序批次"
        if batch_id in descendant_ids:
            return "后序批次"
        return "关联批次"

    ordered_batches = sorted(
        trace.batches,
        key=lambda item: (
            0 if item.id in ancestor_ids else 1 if item.id == root_batch.id else 2,
            item.batch_no,
        ),
    )

    lines = [
        f"## 批次全链路追溯 · {batch_no}",
        "",
        f"> 共关联 **{len(trace.batches)}** 个批次：前序 {len(ancestor_ids)} 个，后序 {len(descendant_ids)} 个。",
        "",
        "### 批次关系与进度",
        "",
        "| 关系 | 批次 | 产品 | 状态 | 当前工序 | 已完成工序 |",
        "|---|---|---|---|---|---|",
    ]
    for trace_batch in ordered_batches:
        current, completed = describe_progress(trace_batch)
        quantity = (
            f" · {trace_batch.quantity:g}{trace_batch.unit or ''}"
            if trace_batch.quantity is not None
            else ""
        )
        lines.append(
            "| "
            f"{relation_label(trace_batch.id)} | `{trace_batch.batch_no}` | "
            f"{product_names.get(trace_batch.product_id, '—')}{quantity} | "
            f"{_BATCH_STATUS_CN.get(trace_batch.status, trace_batch.status)} | "
            f"{current} | {completed} |"
        )

    if trace.links:
        lines.extend(["", "### 流转关系", ""])
        for link in trace.links:
            parent = batches_by_id.get(link.parent_batch_id)
            child = batches_by_id.get(link.child_batch_id)
            if not parent or not child:
                continue
            quantity = f"（分配 {link.allocated_qty:g}）" if link.allocated_qty is not None else ""
            deviation = " · 偏离流转" if link.is_deviation else ""
            lines.append(f"- `{parent.batch_no}` → `{child.batch_no}`{quantity}{deviation}")

    return ToolResult(content="\n".join(lines))
