"""生产-分配管理 HTTP 路由。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.production.schemas.assignment import (
    NodeAssignmentCreate,
    StageAssignmentCreate,
)
from app.modules.production.service import assignment_service
from app.platform.permission.deps import RequireUser

router = APIRouter(tags=["生产-分配管理"])


@router.get("/stage-assignments", summary="工段负责人列表")
async def list_stage_assignments(
    current_user: RequireUser,
    route_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    items = await assignment_service.list_stage_assignments(db, route_id=route_id)
    return success_response(data=items)


@router.post("/stage-assignments", summary="新增工段负责人")
async def create_stage_assignment(
    current_user: RequireUser,
    body: StageAssignmentCreate,
    db: AsyncSession = Depends(get_db),
):
    item = await assignment_service.create_stage_assignment(
        db, user_id=body.user_id, stage_name=body.stage_name,
        route_id=body.route_id, created_by=current_user.id,
    )
    return success_response(data=item)


@router.delete("/stage-assignments/{assignment_id}", summary="删除工段负责人")
async def delete_stage_assignment(
    assignment_id: uuid.UUID,
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    await assignment_service.delete_stage_assignment(db, assignment_id)
    return success_response()


@router.get("/node-assignments", summary="工序负责人列表（默认按当前用户过滤）")
async def list_node_assignments(
    current_user: RequireUser,
    route_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    assigned_by: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    # 默认按当前用户过滤，保证各工段负责人只看到自己配置的默认值
    filter_assigned_by = assigned_by if assigned_by is not None else current_user.id
    items = await assignment_service.list_node_assignments(
        db, route_id=route_id, node_id=node_id, assigned_by=filter_assigned_by,
    )
    return success_response(data=items)


@router.post("/node-assignments", summary="新增/更新工序负责人")
async def create_node_assignment(
    current_user: RequireUser,
    body: NodeAssignmentCreate,
    db: AsyncSession = Depends(get_db),
):
    item = await assignment_service.create_node_assignment(
        db, user_id=body.user_id, node_id=body.node_id,
        route_id=body.route_id, assigned_by=current_user.id,
    )
    return success_response(data=item)


@router.delete("/node-assignments/{assignment_id}", summary="删除工序负责人")
async def delete_node_assignment(
    assignment_id: uuid.UUID,
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
):
    await assignment_service.delete_node_assignment(db, assignment_id)
    return success_response()
