"""批次数据查询。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch
from app.modules.production.repository.trace import trace_links_multi

__all__ = [
    "get_batch",
    "get_batch_by_no",
    "get_batches_by_ids",
    "get_parent_links",
    "list_batches",
    "list_batches_started_within",
    "list_descendant_batch_ids",
    "count_unfinished_batches",
    "count_unfinished_batches_by_route",
]


async def get_parent_links(
    db: AsyncSession, child_ids: set[uuid.UUID],
) -> dict[uuid.UUID, uuid.UUID]:
    """批量查 child→parent 链接（谱系上溯，单线假设父唯一）。"""
    from app.modules.production.models.batch import BatchLink

    if not child_ids:
        return {}
    stmt = select(BatchLink.child_batch_id, BatchLink.parent_batch_id).where(
        BatchLink.child_batch_id.in_(child_ids),
        BatchLink.is_deleted == False,  # noqa: E712
    )
    return {child_id: parent_id for child_id, parent_id in (await db.execute(stmt)).all()}


async def get_batch(db: AsyncSession, batch_id: uuid.UUID) -> Batch | None:
    stmt = select(Batch).where(Batch.id == batch_id, Batch.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_batch_by_no(db: AsyncSession, batch_no: str) -> Batch | None:
    stmt = select(Batch).where(
        Batch.batch_no == batch_no, Batch.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_batches_by_ids(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> list[Batch]:
    if not batch_ids:
        return []
    stmt = select(Batch).where(Batch.id.in_(batch_ids), Batch.is_deleted == False)  # noqa: E712
    return list((await db.execute(stmt)).scalars())


async def list_batches(
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
    stmt = select(Batch).where(Batch.is_deleted == False)  # noqa: E712
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if status:
        stmt = stmt.where(Batch.status == status)
    if route_id:
        stmt = stmt.where(Batch.route_id == route_id)
    if entry_node_filter == "root":
        stmt = stmt.where(Batch.entry_node_id.is_(None))
    elif entry_node_filter == "derived":
        stmt = stmt.where(Batch.entry_node_id.isnot(None))
    if keyword:
        stmt = stmt.where(Batch.batch_no.ilike(f"%{keyword}%"))
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    sort_col = {"batch_no": Batch.batch_no, "created_at": Batch.created_at}.get(
        order_by, Batch.created_at
    )
    stmt = (
        stmt.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), total


async def count_unfinished_batches(db: AsyncSession, product_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Batch)
        .where(
            Batch.product_id == product_id,
            Batch.status.in_(("pending", "in_progress")),
            Batch.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def count_unfinished_batches_by_route(db: AsyncSession, route_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Batch)
        .where(
            Batch.route_id == route_id,
            Batch.status.in_(("pending", "in_progress")),
            Batch.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def list_batches_started_within(
    db: AsyncSession,
    start_dt: datetime | None,
    end_dt: datetime | None,
    route_ids: set[uuid.UUID],
) -> list[uuid.UUID]:
    """返回首工序开始时间落在 ``[start_dt, end_dt)`` 内的批次 id（限定路线）。

    日期范围按批次"开始"的语义取 ``first_started_at``；两个边界均可选，
    ``end_dt`` 为排他上界（调用方换算成次日零点）。
    """
    if not route_ids:
        return []
    stmt = select(Batch.id).where(
        Batch.route_id.in_(route_ids),
        Batch.is_deleted == False,  # noqa: E712
    )
    if start_dt is not None:
        stmt = stmt.where(Batch.first_started_at >= start_dt)
    if end_dt is not None:
        stmt = stmt.where(Batch.first_started_at < end_dt)
    return list((await db.execute(stmt)).scalars())


async def list_descendant_batch_ids(
    db: AsyncSession, root_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    """沿 ``batch_links`` 递归下溯，返回 ``root_ids`` 的全部后代批 id（不含自身）。

    只收集批 id，批次对象与路线的过滤由调用方处理；复用谱系回溯的
    递归 CTE（防环、深度上限 20），一次查询完成。
    """
    if not root_ids:
        return set()
    rows = await trace_links_multi(db, root_ids, "down")
    return {r.child_batch_id for r in rows} - root_ids
