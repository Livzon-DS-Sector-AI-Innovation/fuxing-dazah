"""工段工序负责人分配数据查询。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models.assignment import NodeAssignment, StageAssignment


async def list_stage_assignments(
    db: AsyncSession,
    route_id: uuid.UUID | None = None,
) -> list[StageAssignment]:
    stmt = select(StageAssignment).where(StageAssignment.is_deleted == False)  # noqa: E712
    if route_id:
        stmt = stmt.where(StageAssignment.route_id == route_id)
    return list((await db.execute(stmt)).scalars())


async def create_stage_assignment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    stage_name: str,
    route_id: uuid.UUID,
    created_by: uuid.UUID,
) -> StageAssignment:
    sa = StageAssignment(
        user_id=user_id, stage_name=stage_name,
        route_id=route_id, created_by=created_by,
    )
    db.add(sa)
    await db.flush()
    return sa


async def delete_stage_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> bool:
    stmt = select(StageAssignment).where(
        StageAssignment.id == assignment_id,
        StageAssignment.is_deleted == False,  # noqa: E712
    )
    sa = (await db.execute(stmt)).scalar_one_or_none()
    if not sa:
        return False
    sa.is_deleted = True
    await db.flush()
    return True


async def get_user_stages(db: AsyncSession, user_id: uuid.UUID) -> list[StageAssignment]:
    stmt = select(StageAssignment).where(
        StageAssignment.user_id == user_id,
        StageAssignment.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_node_assignments(
    db: AsyncSession,
    route_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    assigned_by: uuid.UUID | None = None,
) -> list[NodeAssignment]:
    stmt = select(NodeAssignment).where(NodeAssignment.is_deleted == False)  # noqa: E712
    if route_id:
        stmt = stmt.where(NodeAssignment.route_id == route_id)
    if node_id:
        stmt = stmt.where(NodeAssignment.node_id == node_id)
    if assigned_by:
        stmt = stmt.where(NodeAssignment.assigned_by == assigned_by)
    return list((await db.execute(stmt)).scalars())


async def get_node_assignments_by_nodes(
    db: AsyncSession, node_ids: list[uuid.UUID],
) -> list[NodeAssignment]:
    if not node_ids:
        return []
    stmt = select(NodeAssignment).where(
        NodeAssignment.node_id.in_(node_ids),
        NodeAssignment.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def create_node_assignment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    node_id: uuid.UUID,
    route_id: uuid.UUID,
    assigned_by: uuid.UUID,
    created_by: uuid.UUID | None = None,
) -> NodeAssignment:
    na = NodeAssignment(
        user_id=user_id, node_id=node_id,
        route_id=route_id, assigned_by=assigned_by,
        created_by=created_by,
    )
    db.add(na)
    await db.flush()
    return na


async def delete_node_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> bool:
    stmt = select(NodeAssignment).where(
        NodeAssignment.id == assignment_id,
        NodeAssignment.is_deleted == False,  # noqa: E712
    )
    na = (await db.execute(stmt)).scalar_one_or_none()
    if not na:
        return False
    na.is_deleted = True
    await db.flush()
    return True


async def get_user_node_assignments(
    db: AsyncSession, user_id: uuid.UUID,
) -> list[NodeAssignment]:
    stmt = select(NodeAssignment).where(
        NodeAssignment.user_id == user_id,
        NodeAssignment.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
