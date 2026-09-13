"""生产分析数据查询。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch, NodeExecution

__all__ = [
    "list_step_cycle_samples",
    "count_active_batches",
]


async def list_step_cycle_samples(
    db: AsyncSession,
    *,
    route_ids: set[uuid.UUID],
    node_ids: set[uuid.UUID],
    product_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> list[dict]:
    """查询工序周期原始样本，聚合与血缘归并由服务层完成。

    ``route_ids`` 是目标已发布路线及其祖先路线的并集，``node_ids`` 是这些路线
    上的节点并集。只取首次完成执行，避免回流重做污染周期样本；时间范围按工序
    开始时间筛选。
    """
    if not route_ids or not node_ids:
        return []

    duration_sec = func.extract(
        "epoch", NodeExecution.finished_at - NodeExecution.started_at
    )
    stmt = (
        select(
            NodeExecution.node_id,
            Batch.route_id,
            duration_sec.label("duration_sec"),
        )
        .select_from(NodeExecution)
        .join(
            Batch,
            (Batch.id == NodeExecution.batch_id)
            & (Batch.is_deleted == False),  # noqa: E712
        )
        .where(
            NodeExecution.node_id.in_(node_ids),
            Batch.route_id.in_(route_ids),
            NodeExecution.status == "completed",
            NodeExecution.finished_at.is_not(None),
            NodeExecution.execution_seq == 1,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
    )
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if since:
        stmt = stmt.where(NodeExecution.started_at >= since)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "route_id": r.route_id,
            "node_id": r.node_id,
            "duration_sec": float(r.duration_sec),
        }
        for r in rows
    ]


async def count_active_batches(
    db: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    route_ids: set[uuid.UUID] | None = None,
    product_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> int:
    """统计在产/已完成的批次数（含 in_progress 和 completed）。

    ``route_ids`` 用于工艺路线血缘场景，按批次路线集合去重计数；与 ``route_id``
    互斥，保留后者以兼容单路线调用。
    """
    stmt = select(func.count()).select_from(Batch).where(
        Batch.status.in_(("in_progress", "completed")),
        Batch.is_deleted == False,  # noqa: E712
    )
    if route_id:
        stmt = stmt.where(Batch.route_id == route_id)
    elif route_ids is not None:
        if not route_ids:
            return 0
        stmt = stmt.where(Batch.route_id.in_(route_ids))
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if since:
        stmt = stmt.where(Batch.created_at >= since)
    return int((await db.execute(stmt)).scalar_one())
