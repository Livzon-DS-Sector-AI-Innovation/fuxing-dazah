"""全链路溯源：沿 batch_links 双向递归，组装批次 + 谱系边 + 执行摘要。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.production import repository as repo
from app.modules.production.schemas import (
    TraceBatch,
    TraceExecutionBrief,
    TraceLink,
    TraceOut,
)


async def get_trace(db: AsyncSession, batch_id: uuid.UUID) -> TraceOut:
    root = await repo.get_batch(db, batch_id)
    if not root:
        raise NotFoundException("批次", str(batch_id))

    up_rows = await repo.trace_links(db, batch_id, "up")
    down_rows = await repo.trace_links(db, batch_id, "down")

    links_by_pair: dict[tuple[uuid.UUID, uuid.UUID], TraceLink] = {}
    for row in [*up_rows, *down_rows]:
        pair = (row.parent_batch_id, row.child_batch_id)
        if pair not in links_by_pair:
            links_by_pair[pair] = TraceLink(
                parent_batch_id=row.parent_batch_id,
                child_batch_id=row.child_batch_id,
                edge_id=row.edge_id,
                allocated_qty=row.allocated_qty,
                is_deviation=row.is_deviation,
            )
    links = list(links_by_pair.values())

    batch_ids = {batch_id}
    for link in links:
        batch_ids.add(link.parent_batch_id)
        batch_ids.add(link.child_batch_id)

    batches = await repo.get_batches_by_ids(db, list(batch_ids))
    executions = await repo.list_executions_by_batches(db, list(batch_ids))
    exec_ids = [e.id for e in executions]
    values = await repo.get_field_values_by_executions(db, exec_ids)
    nodes = await repo.get_nodes_by_ids(db, list({e.node_id for e in executions}))
    node_names = {n.id: n.name for n in nodes}
    node_stages = {n.id: n.stage_name for n in nodes}

    # 每批最新 execution 所在节点 → 当前工段
    batch_latest_node: dict[uuid.UUID, uuid.UUID] = {}
    for e in sorted(executions, key=lambda x: x.started_at):
        batch_latest_node[e.batch_id] = e.node_id
    batch_stages = {bid: node_stages.get(nid) for bid, nid in batch_latest_node.items()}

    abnormal_by_exec: dict[uuid.UUID, int] = {}
    for v in values:
        if v.is_abnormal:
            abnormal_by_exec[v.execution_id] = abnormal_by_exec.get(v.execution_id, 0) + 1

    briefs_by_batch: dict[uuid.UUID, list[TraceExecutionBrief]] = {}
    for e in executions:
        briefs_by_batch.setdefault(e.batch_id, []).append(
            TraceExecutionBrief(
                node_name=node_names.get(e.node_id, ""),
                status=e.status,
                owner_name=e.owner_name,
                started_at=e.started_at,
                finished_at=e.finished_at,
                is_deviation=e.is_deviation,
                abnormal_count=abnormal_by_exec.get(e.id, 0),
            )
        )

    trace_batches = [
        TraceBatch(
            id=b.id,
            batch_no=b.batch_no,
            product_id=b.product_id,
            status=b.status,
            quantity=b.quantity,
            unit=b.unit,
            current_stage_name=batch_stages.get(b.id),
            executions=briefs_by_batch.get(b.id, []),
        )
        for b in batches
    ]
    return TraceOut(root_batch_id=batch_id, batches=trace_batches, links=links)
