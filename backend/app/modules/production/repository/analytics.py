"""生产分析数据查询。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    Batch,
    NodeExecution,
    NodeFieldValue,
    RouteNode,
)

__all__ = [
    "get_step_cycle_stats",
    "count_active_batches",
    "get_field_trend_values",
]


async def get_step_cycle_stats(
    db: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> list[dict]:
    """按工序聚合已完成执行的耗时统计。

    仅统计首次执行(execution_seq=1)，排除中止和未完成的记录。
    """
    duration_sec = func.extract(
        "epoch", NodeExecution.finished_at - NodeExecution.started_at
    )
    stmt = (
        select(
            RouteNode.id.label("node_id"),
            RouteNode.name.label("node_name"),
            RouteNode.stage_name,
            RouteNode.sort_order,
            func.count().label("n"),
            (func.avg(duration_sec) / 3600.0).label("avg_hours"),
            (func.min(duration_sec) / 3600.0).label("min_hours"),
            (func.max(duration_sec) / 3600.0).label("max_hours"),
        )
        .select_from(NodeExecution)
        .join(RouteNode, RouteNode.id == NodeExecution.node_id)
        .where(
            NodeExecution.status == "completed",
            NodeExecution.finished_at.is_not(None),
            NodeExecution.execution_seq == 1,
            NodeExecution.is_deleted == False,  # noqa: E712
            RouteNode.is_deleted == False,  # noqa: E712
        )
    )
    if route_id:
        stmt = stmt.join(Batch, Batch.id == NodeExecution.batch_id).where(
            Batch.route_id == route_id,
            Batch.is_deleted == False,  # noqa: E712
        )
    if product_id:
        if not route_id:
            stmt = stmt.join(Batch, Batch.id == NodeExecution.batch_id)
        stmt = stmt.where(
            Batch.product_id == product_id,
            Batch.is_deleted == False,  # noqa: E712
        )
    if since:
        stmt = stmt.where(NodeExecution.started_at >= since)

    stmt = stmt.group_by(
        RouteNode.id, RouteNode.name, RouteNode.stage_name, RouteNode.sort_order
    ).order_by(RouteNode.sort_order)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "node_id": r.node_id,
            "node_name": r.node_name,
            "stage_name": r.stage_name,
            "sort_order": r.sort_order,
            "n": r.n,
            "avg_hours": round(float(r.avg_hours), 2),
            "min_hours": round(float(r.min_hours), 2) if r.min_hours else None,
            "max_hours": round(float(r.max_hours), 2) if r.max_hours else None,
        }
        for r in rows
    ]


async def count_active_batches(
    db: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> int:
    """统计在产/已完成的批次数（含 in_progress 和 completed）。"""
    stmt = select(func.count()).select_from(Batch).where(
        Batch.status.in_(("in_progress", "completed")),
        Batch.is_deleted == False,  # noqa: E712
    )
    if route_id:
        stmt = stmt.where(Batch.route_id == route_id)
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if since:
        stmt = stmt.where(Batch.created_at >= since)
    return int((await db.execute(stmt)).scalar_one())


async def get_field_trend_values(
    db: AsyncSession, node_id: uuid.UUID, field_key: str
) -> list[tuple[str, datetime, float]]:
    """节点下所有完成执行的该字段值，按填写时间升序；返回 (batch_no, filled_at, value)。"""
    stmt = (
        select(Batch.batch_no, NodeFieldValue.filled_at, NodeFieldValue.value_numeric)
        .select_from(NodeFieldValue)
        .join(NodeExecution, NodeExecution.id == NodeFieldValue.execution_id)
        .join(Batch, Batch.id == NodeExecution.batch_id)
        .where(
            NodeExecution.node_id == node_id,
            NodeExecution.status == "completed",
            NodeFieldValue.field_key == field_key,
            NodeFieldValue.value_numeric.is_not(None),
            NodeFieldValue.filled_at.is_not(None),
            NodeExecution.is_deleted == False,  # noqa: E712
            NodeFieldValue.is_deleted == False,  # noqa: E712
            Batch.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeFieldValue.filled_at)
    )
    return [(r.batch_no, r.filled_at, r.value_numeric) for r in (await db.execute(stmt)).all()]
