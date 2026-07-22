"""批次数据查询。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch

__all__ = [
    "get_batch",
    "get_batch_by_no",
    "get_batches_by_ids",
    "list_batches",
    "count_unfinished_batches",
]


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
