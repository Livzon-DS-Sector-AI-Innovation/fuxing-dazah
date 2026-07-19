"""谱系溯源数据查询 — batch_links 递归 CTE。"""

import uuid
from typing import Any, Literal

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["trace_links"]

_TRACE_UP_SQL = text(
    """
WITH RECURSIVE up AS (
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, ARRAY[l.child_batch_id] AS path, 1 AS depth
    FROM production.batch_links l
    WHERE l.child_batch_id = :bid AND l.is_deleted = false
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
    WHERE l.parent_batch_id = :bid AND l.is_deleted = false
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
    sql = _TRACE_UP_SQL if direction == "up" else _TRACE_DOWN_SQL
    result = await db.execute(sql, {"bid": batch_id})
    return list(result.all())
