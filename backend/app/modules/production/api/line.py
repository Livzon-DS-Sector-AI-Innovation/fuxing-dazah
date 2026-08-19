"""生产-产线管理 HTTP 路由。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.production.schemas.line import (
    LineAssignmentCreate,
    LineCreate,
    LineUpdate,
)
from app.modules.production.service import line_service
from app.platform.identity.models import User
from app.platform.permission.deps import RequireUser, require_permission

router = APIRouter(tags=["生产-产线管理"])
_manage = require_permission("production:process:manage")
_read = require_permission("production:batch:read")


# ── 产线字典 ──


@router.get("/lines", summary="产线列表")
async def list_lines(
    _user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
):
    items = await line_service.list_lines(db)
    return success_response(data=[i.model_dump(mode="json") for i in items])


@router.post("/lines", summary="新增产线")
async def create_line(
    body: LineCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
):
    item = await line_service.create_line(db, body, user)
    return success_response(data=item.model_dump(mode="json"))


@router.put("/lines/{line_id}", summary="编辑产线")
async def update_line(
    line_id: uuid.UUID,
    body: LineUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
):
    item = await line_service.update_line(db, line_id, body, user)
    return success_response(data=item.model_dump(mode="json"))


@router.delete("/lines/{line_id}", summary="删除产线（软删，级联解绑）")
async def delete_line(
    line_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
):
    await line_service.delete_line(db, line_id, user)
    return success_response()


# ── 用户-产线绑定 ──


@router.get("/line-assignments", summary="产线绑定列表")
async def list_line_assignments(
    current_user: RequireUser,
    line_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    # 都不传：返回当前登录用户的绑定（结束工序弹窗候选）
    # 传 line_id：返回该产线全部绑定（管理页）
    # 传 user_id：返回该用户绑定（批次负责人兜底候选）
    filter_user_id = user_id if user_id is not None else (None if line_id else current_user.id)
    items = await line_service.list_line_assignments(
        db, line_id=line_id, user_id=filter_user_id,
    )
    return success_response(data=[i.model_dump(mode="json") for i in items])


@router.post("/line-assignments", summary="绑定用户到产线")
async def create_line_assignment(
    body: LineAssignmentCreate,
    current_user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
):
    item = await line_service.bind_user_line(
        db, user_id=body.user_id, line_id=body.line_id,
        created_by=current_user.id,
    )
    return success_response(data=item.model_dump(mode="json"))


@router.delete("/line-assignments/{assignment_id}", summary="解除产线绑定")
async def delete_line_assignment(
    assignment_id: uuid.UUID,
    _current_user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
):
    await line_service.unbind_user_line(db, assignment_id)
    return success_response()
