"""谱系溯源数据查询 — batch_links 递归 CTE。"""

import uuid
from typing import Any, Literal

from sqlalchemy import Row, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["trace_links", "trace_links_multi"]

_TRACE_UP_SQL = text(
    """
WITH RECURSIVE up AS (
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, ARRAY[l.child_batch_id] AS path, 1 AS depth
    FROM production.batch_links l
    WHERE l.child_batch_id IN :bids AND l.is_deleted = false
    UNION ALL
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, up.path || l.child_batch_id, up.depth + 1
    FROM production.batch_links l
    JOIN up ON l.child_batch_id = up.parent_batch_id
    WHERE l.is_deleted = false
      AND NOT (l.parent_batch_id = ANY(up.path))
      AND up.depth < 20
)
SELECT parent_batch_id, child_batch_id, edge_id, allocated_qty, is_deviation FROM up
"""
)

_TRACE_DOWN_SQL = text(
    """
WITH RECURSIVE down AS (
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, ARRAY[l.parent_batch_id] AS path, 1 AS depth
    FROM production.batch_links l
    WHERE l.parent_batch_id IN :bids AND l.is_deleted = false
    UNION ALL
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, down.path || l.parent_batch_id, down.depth + 1
    FROM production.batch_links l
    JOIN down ON l.parent_batch_id = down.child_batch_id
    WHERE l.is_deleted = false
      AND NOT (l.child_batch_id = ANY(down.path))
      AND down.depth < 20
)
SELECT parent_batch_id, child_batch_id, edge_id, allocated_qty, is_deviation FROM down
"""
)


async def trace_links(
    db: AsyncSession, batch_id: uuid.UUID, direction: Literal["up", "down"]
) -> list[Row[Any]]:
    """沿 batch_links 递归上溯/下溯，返回谱系边行（防环、深度上限 20）。"""
    return await trace_links_multi(db, {batch_id}, direction)


async def trace_links_multi(
    db: AsyncSession, batch_ids: set[uuid.UUID], direction: Literal["up", "down"],
) -> list[Row[Any]]:
    """多根谱系边查询：``batch_ids`` 各自递归上溯/下溯，一次 CTE 完成。

    注意：多根共享祖先（up）或后代（down）时，共享边会按根数重复出现；
    需要去重的调用方自行用集合收口（如 ``list_descendant_batch_ids``）。
    """
    if not batch_ids:
        return []
    sql = _TRACE_UP_SQL if direction == "up" else _TRACE_DOWN_SQL
    sql = sql.bindparams(bindparam("bids", expanding=True))
    result = await db.execute(sql, {"bids": list(batch_ids)})
    return list(result.all())
