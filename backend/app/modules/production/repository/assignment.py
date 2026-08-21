"""工段工序负责人分配数据查询。"""

import uuid

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import RouteNode
from app.modules.production.models.assignment import (
    NodeAssignment,
    StageAssignment,
    StageSuffix,
)


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


async def get_user_node_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """用户负责的全部节点 id：工段负责人（工段下全部节点）+ 工序负责人（节点直取）。"""
    node_ids: set[uuid.UUID] = set()
    stages = await get_user_stages(db, user_id)
    if stages:
        stmt = select(RouteNode.id).where(
            tuple_(RouteNode.route_id, RouteNode.stage_name).in_(
                [(sa.route_id, sa.stage_name) for sa in stages]
            ),
            RouteNode.is_deleted == False,  # noqa: E712
        )
        node_ids.update((await db.execute(stmt)).scalars())
    for na in await get_user_node_assignments(db, user_id):
        node_ids.add(na.node_id)
    return node_ids


# ── 工段批次尾缀 ──


async def set_stage_suffix(
    db: AsyncSession,
    *,
    route_id: uuid.UUID,
    stage_name: str,
    suffix: str,
    updated_by: uuid.UUID,
) -> StageSuffix:
    """upsert：活跃行更新；已软删行复活；无则新建（避免增删增触发唯一索引）。

    并发首次写入撞唯一索引时经 savepoint 回滚后重走更新路径。
    """
    stmt = (
        select(StageSuffix)
        .where(
            StageSuffix.route_id == route_id,
            StageSuffix.stage_name == stage_name,
        )
        .order_by(StageSuffix.created_at.desc())
        .limit(1)
    )
    row: StageSuffix | None = None
    for _attempt in range(2):
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = StageSuffix(
                route_id=route_id, stage_name=stage_name,
                suffix=suffix, created_by=updated_by, updated_by=updated_by,
            )
            try:
                async with db.begin_nested():
                    db.add(row)
                    await db.flush()
            except IntegrityError:
                continue
            return row
        break
    if row is None:
        # 连续两次撞唯一索引（竞态方一直未提交），极其罕见，直接失败
        raise RuntimeError("工段尾缀并发写入重试失败")
    # UPDATE 后 updated_at 不回填，必须 select re-fetch（async 铁律）
    row.suffix = suffix
    row.is_deleted = False
    row.updated_by = updated_by
    await db.flush()
    refreshed = (
        await db.execute(select(StageSuffix).where(StageSuffix.id == row.id))
    ).scalar_one()
    return refreshed


async def list_stage_suffixes(
    db: AsyncSession, route_ids: list[uuid.UUID] | None = None,
) -> list[StageSuffix]:
    stmt = select(StageSuffix).where(StageSuffix.is_deleted == False)  # noqa: E712
    if route_ids:
        stmt = stmt.where(StageSuffix.route_id.in_(route_ids))
    return list((await db.execute(stmt)).scalars())
