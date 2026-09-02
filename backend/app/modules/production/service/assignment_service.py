"""工段工序负责人分配服务。"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.production.repository import assignment as repo
from app.modules.production.repository import route as route_repo
from app.modules.production.schemas.assignment import (
    NodeAssignmentOut,
    StageAssignmentOut,
    StageSuffixOut,
)
from app.platform.permission.deps import get_user_permissions

if TYPE_CHECKING:
    from app.modules.production.models.batch import Batch
    from app.modules.production.models.execution import NodeExecution

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


# ── 工段批次尾缀 ──


async def _published_route_ids(
    db: AsyncSession, route_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    """已发布路线的 ID 集合（草稿/已归档路线不参与尾缀配置）。"""
    routes = await route_repo.get_routes_by_ids(db, list(route_ids))
    return {r.id for r in routes if r.status == "published"}


async def list_my_stage_suffixes(
    db: AsyncSession, user_id: uuid.UUID,
) -> list[StageSuffixOut]:
    """当前用户负责工段的尾缀列表（未配置的工段返回空尾缀）。

    仅包含已发布路线的工段，与工作台 assigned_routes 保持一致。
    """
    stages = await repo.get_user_stages(db, user_id)
    if not stages:
        return []
    published = await _published_route_ids(db, {s.route_id for s in stages})
    stages = [s for s in stages if s.route_id in published]
    if not stages:
        return []
    keys = sorted({(s.route_id, s.stage_name) for s in stages})
    rows = await repo.list_stage_suffixes(
        db, list({s.route_id for s in stages}),
    )
    suffix_map = {(r.route_id, r.stage_name): r for r in rows}
    result = []
    for route_id, stage_name in keys:
        row = suffix_map.get((route_id, stage_name))
        result.append(
            StageSuffixOut.model_validate(row)
            if row
            else StageSuffixOut(route_id=route_id, stage_name=stage_name, suffix="")
        )
    return result


async def set_stage_suffix(
    db: AsyncSession, *, user_id: uuid.UUID, route_id: uuid.UUID,
    stage_name: str, suffix: str,
) -> StageSuffixOut:
    """设置工段尾缀。仅该工段负责人可设置（管理员放行），且仅已发布路线。"""
    published = await _published_route_ids(db, {route_id})
    if route_id not in published:
        raise ForbiddenException("工艺路线未发布，无法设置尾缀")
    stages = await repo.get_user_stages(db, user_id)
    if not any(s.route_id == route_id and s.stage_name == stage_name for s in stages):
        perms = await get_user_permissions(str(user_id), db)
        if "production:batch:submit" not in perms:
            raise ForbiddenException("您不是该工段的负责人，无法设置尾缀")
    row = await repo.set_stage_suffix(
        db, route_id=route_id, stage_name=stage_name,
        suffix=suffix, updated_by=user_id,
    )
    return StageSuffixOut.model_validate(row)


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


async def require_batch_owner_access(user_id: uuid.UUID, batch: "Batch") -> None:
    """批次归属校验：无主=共享可操作；归属自己=可操作；归属他人=Forbidden。

    管理员（production:batch:submit）在调用方先行放行。
    """
    if batch.owner_user_id is None or batch.owner_user_id == user_id:
        return
    raise ForbiddenException("该批次归属其他负责人，仅读")


async def require_operator_access(
    db: AsyncSession,
    user_id: uuid.UUID,
    node_id: uuid.UUID,
    route_id: uuid.UUID,
    stage_name: str | None,
    batch: "Batch | None",
    execution: "NodeExecution | None" = None,
) -> None:
    """执行层工序操作权限：工段/工序负责人校验 + 归属他人批次的豁免。

    合并 require_stage_permission 与 has_node_assignment 的两次
    NodeAssignment 查询为一次：工段不匹配时用于权限兜底，归属他人批次时
    用于豁免判定。归属规则复用 require_batch_owner_access。

    单次执行负责人（开始工序时指定的 execution.owner_id）直接放行：
    实际执行人可结束/补录/中止自己这一次执行，不受批次归属隔离限制；
    该豁免不授予任何其他批次或工序的操作权。
    """
    if (
        execution is not None
        and execution.owner_id == user_id
        # 豁免仅对"操作对象就是该执行"生效，防止调用方误传其他执行绕过工段/归属校验
        and execution.node_id == node_id
        and (batch is None or execution.batch_id == batch.id)
    ):
        return
    if stage_name is None:
        raise ForbiddenException("您没有该工段的操作权限")
    has_stage = any(
        s.stage_name == stage_name and s.route_id == route_id
        for s in await repo.get_user_stages(db, user_id)
    )
    owner_batch = (
        batch
        if batch is not None and batch.owner_user_id not in (None, user_id)
        else None
    )
    node_assigned = False
    if not has_stage or owner_batch is not None:
        user_nodes = await repo.get_user_node_assignments(db, user_id)
        node_assigned = any(
            n.node_id == node_id and n.route_id == route_id for n in user_nodes
        )
    if not has_stage and not node_assigned:
        raise ForbiddenException("您没有该工段的操作权限")
    if owner_batch is not None and not node_assigned:
        await require_batch_owner_access(user_id, owner_batch)
