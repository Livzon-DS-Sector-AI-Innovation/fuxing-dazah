"""工序执行数据查询。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    Batch,
    BatchIntermediateOutput,
    NodeExecution,
    NodeExecutionEquipment,
    NodeFieldValue,
    RouteNode,
)

__all__ = [
    "get_execution",
    "get_last_completed_execution",
    "list_executions",
    "list_executions_by_batches",
    "count_executions",
    "max_execution_seq",
    "has_in_progress_execution",
    "completed_node_ids",
    "get_completed_node_ids_by_batches",
    "in_progress_node_ids",
    "get_field_values_by_executions",
    "get_equipments_by_executions",
    "get_nodes_by_ids",
    "list_executions_by_node",
    "list_completed_executions_by_nodes",
    "group_latest_completed_by_batch_node",
    "find_duplicate_output_batch_nos",
]


async def get_execution(
    db: AsyncSession, execution_id: uuid.UUID
) -> NodeExecution | None:
    stmt = select(NodeExecution).where(
        NodeExecution.id == execution_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_executions(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[NodeExecution]:
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at)
    )
    return list((await db.execute(stmt)).scalars())


async def get_last_completed_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID | None = None
) -> NodeExecution | None:
    """获取批次最后一个完成的执行（按 finished_at 降序）；node_id 给定时限定该节点。"""
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.status == "completed",
            NodeExecution.finished_at.is_not(None),
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.finished_at.desc())
        .limit(1)
    )
    if node_id is not None:
        stmt = stmt.where(NodeExecution.node_id == node_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_executions_by_batches(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> list[NodeExecution]:
    if not batch_ids:
        return []
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id.in_(batch_ids),
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at)
    )
    return list((await db.execute(stmt)).scalars())


async def count_executions(db: AsyncSession, batch_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one())


async def max_execution_seq(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID
) -> int:
    stmt = select(func.coalesce(func.max(NodeExecution.execution_seq), 0)).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.node_id == node_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one())


async def has_in_progress_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID
) -> bool:
    stmt = select(func.count()).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.node_id == node_id,
        NodeExecution.status == "in_progress",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one()) > 0


async def get_completed_node_ids_by_batches(
    db: AsyncSession, batch_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    """批量查询：这些批次上所有 completed 执行的节点 id 集合。"""
    if not batch_ids:
        return set()
    stmt = select(NodeExecution.node_id).where(
        NodeExecution.batch_id.in_(batch_ids),
        NodeExecution.status == "completed",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return set((await db.execute(stmt)).scalars())


async def completed_node_ids(
    db: AsyncSession, batch_id: uuid.UUID
) -> set[uuid.UUID]:
    return await get_completed_node_ids_by_batches(db, [batch_id])


async def in_progress_node_ids(
    db: AsyncSession, batch_id: uuid.UUID
) -> set[uuid.UUID]:
    stmt = select(NodeExecution.node_id).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.status == "in_progress",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return set((await db.execute(stmt)).scalars())


async def get_field_values_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[NodeFieldValue]:
    if not execution_ids:
        return []
    stmt = select(NodeFieldValue).where(
        NodeFieldValue.execution_id.in_(execution_ids),
        NodeFieldValue.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_completed_executions_by_nodes(
    db: AsyncSession,
    node_ids: list[uuid.UUID],
    batch_ids: list[uuid.UUID] | None = None,
) -> list[NodeExecution]:
    """节点下全部 completed 执行；batch_ids 给定时限定批次（谱系内取数，避免全表扫描）。"""
    if not node_ids:
        return []
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.node_id.in_(node_ids),
            NodeExecution.status == "completed",
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at)
    )
    if batch_ids is not None:
        stmt = stmt.where(NodeExecution.batch_id.in_(batch_ids))
    return list((await db.execute(stmt)).scalars())


def group_latest_completed_by_batch_node(
    executions: list[NodeExecution],
) -> dict[tuple[uuid.UUID, uuid.UUID], NodeExecution]:
    """(batch_id, node_id) → finished_at 最新一条 completed 执行。

    回流场景同批同节点可能有多条 completed 执行；取数口径与计算字段/批次详情保持一致。
    """
    latest: dict[tuple[uuid.UUID, uuid.UUID], NodeExecution] = {}
    for e in executions:
        key = (e.batch_id, e.node_id)
        prev = latest.get(key)
        if prev is None or (
            e.finished_at is not None
            and (prev.finished_at is None or e.finished_at > prev.finished_at)
        ):
            latest[key] = e
    return latest


async def get_equipments_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[NodeExecutionEquipment]:
    if not execution_ids:
        return []
    stmt = select(NodeExecutionEquipment).where(
        NodeExecutionEquipment.execution_id.in_(execution_ids),
        NodeExecutionEquipment.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_nodes_by_ids(
    db: AsyncSession, node_ids: list[uuid.UUID]
) -> list[RouteNode]:
    if not node_ids:
        return []
    stmt = select(RouteNode).where(
        RouteNode.id.in_(node_ids), RouteNode.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_executions_by_node(
    db: AsyncSession,
    node_id: uuid.UUID,
    status: str | None,
    page: int,
    page_size: int,
    order_by: str = "started_at",
    order: str = "desc",
) -> tuple[list[NodeExecution], int]:
    stmt = select(NodeExecution).where(
        NodeExecution.node_id == node_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    if status:
        stmt = stmt.where(NodeExecution.status == status)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    if order_by == "batch_no":
        # 批号在 batches 表上，仅排序时 join（无外键约束，按 batch_id 关联）
        stmt = stmt.join(Batch, Batch.id == NodeExecution.batch_id)
    sort_col = {
        "batch_no": Batch.batch_no,
        "started_at": NodeExecution.started_at,
    }.get(order_by, NodeExecution.started_at)
    stmt = (
        stmt.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), int(total)


async def find_duplicate_output_batch_nos(
    db: AsyncSession, batch_nos: list[str],
) -> list[str]:
    """返回 batch_nos 中已被未删除产出记录占用的批号（写入前查重，DB 唯一索引兜底并发）。"""
    stmt = select(BatchIntermediateOutput.intermediate_batch_no).where(
        BatchIntermediateOutput.intermediate_batch_no.in_(batch_nos),
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    return [b for b in (await db.execute(stmt)).scalars() if b is not None]
