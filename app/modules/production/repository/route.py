"""工艺路线数据查询。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    NodeFieldDef,
    ProcessRoute,
    RouteEdge,
    RouteNode,
    RouteNodeIntermediate,
)

__all__ = [
    "get_route",
    "get_routes_by_ids",
    "list_routes",
    "next_route_version",
    "get_route_nodes",
    "get_route_edges",
    "get_edge",
    "get_field_defs_by_nodes",
    "soft_delete_route_graph",
]


async def get_route(db: AsyncSession, route_id: uuid.UUID) -> ProcessRoute | None:
    stmt = select(ProcessRoute).where(
        ProcessRoute.id == route_id, ProcessRoute.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_routes_by_ids(
    db: AsyncSession, route_ids: list[uuid.UUID]
) -> list[ProcessRoute]:
    if not route_ids:
        return []
    stmt = select(ProcessRoute).where(
        ProcessRoute.id.in_(route_ids),
        ProcessRoute.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_routes(
    db: AsyncSession, product_id: uuid.UUID | None, page: int, page_size: int
) -> tuple[list[ProcessRoute], int]:
    stmt = select(ProcessRoute).where(ProcessRoute.is_deleted == False)  # noqa: E712
    if product_id:
        stmt = stmt.where(ProcessRoute.product_id == product_id)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(ProcessRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), total


async def next_route_version(db: AsyncSession, product_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(ProcessRoute.version), 0)).where(
        ProcessRoute.product_id == product_id,
        ProcessRoute.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one()) + 1


async def get_route_nodes(db: AsyncSession, route_id: uuid.UUID) -> list[RouteNode]:
    stmt = (
        select(RouteNode)
        .where(RouteNode.route_id == route_id, RouteNode.is_deleted == False)  # noqa: E712
        .order_by(RouteNode.sort_order, RouteNode.node_code)
    )
    return list((await db.execute(stmt)).scalars())


async def get_route_edges(db: AsyncSession, route_id: uuid.UUID) -> list[RouteEdge]:
    stmt = select(RouteEdge).where(
        RouteEdge.route_id == route_id, RouteEdge.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_edge(db: AsyncSession, edge_id: uuid.UUID) -> RouteEdge | None:
    stmt = select(RouteEdge).where(
        RouteEdge.id == edge_id, RouteEdge.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_field_defs_by_nodes(
    db: AsyncSession, node_ids: list[uuid.UUID]
) -> list[NodeFieldDef]:
    if not node_ids:
        return []
    stmt = (
        select(NodeFieldDef)
        .where(NodeFieldDef.node_id.in_(node_ids), NodeFieldDef.is_deleted == False)  # noqa: E712
        .order_by(NodeFieldDef.sort_order)
    )
    return list((await db.execute(stmt)).scalars())


async def soft_delete_route_graph(db: AsyncSession, route_id: uuid.UUID) -> None:
    """整图替换前软删除路线现有节点、边、字段定义、中间体绑定。"""
    nodes = await get_route_nodes(db, route_id)
    node_ids = [n.id for n in nodes]
    for n in nodes:
        n.is_deleted = True
    for e in await get_route_edges(db, route_id):
        e.is_deleted = True
    for f in await get_field_defs_by_nodes(db, node_ids):
        f.is_deleted = True
    im_stmt = select(RouteNodeIntermediate).where(
        RouteNodeIntermediate.node_id.in_(node_ids),
        RouteNodeIntermediate.is_deleted == False,  # noqa: E712
    )
    im_list = list((await db.execute(im_stmt)).scalars())
    for im in im_list:
        im.is_deleted = True
    await db.flush()
