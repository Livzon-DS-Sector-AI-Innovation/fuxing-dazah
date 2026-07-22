"""工段工序负责人分配服务。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.production.repository import assignment as repo
from app.modules.production.schemas.assignment import (
    NodeAssignmentOut,
    StageAssignmentOut,
)

# ── 工段负责人 ──


async def list_stage_assignments(
    db: AsyncSession, *, route_id: uuid.UUID | None = None,
) -> list[StageAssignmentOut]:
    items = await repo.list_stage_assignments(db, route_id=route_id)
    return [StageAssignmentOut.model_validate(sa) for sa in items]


async def create_stage_assignment(
    db: AsyncSession, *, user_id: uuid.UUID, stage_name: str,
    route_id: uuid.UUID, created_by: uuid.UUID,
) -> StageAssignmentOut:
    # 检查是否存在同名活跃记录，避免触发数据库唯一索引异常
    existing = await repo.list_stage_assignments(db, route_id=route_id)
    for sa in existing:
        if sa.user_id == user_id and sa.stage_name == stage_name:
            raise DuplicateException("工段分配", f"用户+{stage_name}")
    sa = await repo.create_stage_assignment(
        db, user_id=user_id, stage_name=stage_name,
        route_id=route_id, created_by=created_by,
    )
    return StageAssignmentOut.model_validate(sa)


async def delete_stage_assignment(
    db: AsyncSession, assignment_id: uuid.UUID,
) -> None:
    ok = await repo.delete_stage_assignment(db, assignment_id)
    if not ok:
        raise NotFoundException("工段分配")


# ── 工序负责人 ──


async def list_node_assignments(
    db: AsyncSession, *, route_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    assigned_by: uuid.UUID | None = None,
) -> list[NodeAssignmentOut]:
    items = await repo.list_node_assignments(
        db, route_id=route_id, node_id=node_id, assigned_by=assigned_by,
    )
    return [NodeAssignmentOut.model_validate(na) for na in items]


async def create_node_assignment(
    db: AsyncSession, *, user_id: uuid.UUID, node_id: uuid.UUID,
    route_id: uuid.UUID, assigned_by: uuid.UUID,
) -> NodeAssignmentOut:
    # 检查是否存在同名活跃记录，避免触发数据库唯一索引异常
    existing = await repo.list_node_assignments(db, node_id=node_id)
    for na in existing:
        if na.user_id == user_id:
            raise DuplicateException("工序分配", "用户+节点")
    na = await repo.create_node_assignment(
        db, user_id=user_id, node_id=node_id,
        route_id=route_id, assigned_by=assigned_by,
        created_by=assigned_by,
    )
    return NodeAssignmentOut.model_validate(na)


async def delete_node_assignment(
    db: AsyncSession, assignment_id: uuid.UUID,
) -> None:
    ok = await repo.delete_node_assignment(db, assignment_id)
    if not ok:
        raise NotFoundException("工序分配")


async def check_stage_permission(
    db: AsyncSession, user_id: uuid.UUID, node_id: uuid.UUID, route_id: uuid.UUID,
    stage_name: str | None,
) -> bool:
    """检查用户是否有该工序节点的工段权限"""
    if stage_name is None:
        return False
    user_stages = await repo.get_user_stages(db, user_id)
    for s in user_stages:
        if s.stage_name == stage_name and s.route_id == route_id:
            return True
    user_nodes = await repo.get_user_node_assignments(db, user_id)
    for n in user_nodes:
        if n.node_id == node_id and n.route_id == route_id:
            return True
    return False


async def require_stage_permission(
    db: AsyncSession, user_id: uuid.UUID, node_id: uuid.UUID,
    route_id: uuid.UUID, stage_name: str | None,
) -> None:
    """检查工段权限，无权限时抛出 ForbiddenException。"""
    if not await check_stage_permission(db, user_id, node_id, route_id, stage_name):
        raise ForbiddenException("您没有该工段的操作权限")
