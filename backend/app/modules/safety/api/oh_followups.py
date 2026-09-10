"""Safety API — oh_followups endpoints（职业健康异常随访闭环）。

对齐 backend-design.md §6.5：
- GET 列表（status/category/person_id 筛选 + 到期排序，expired 为派生展示状态）；
- POST 创建（手动补录，exam_id 或 person_id 必填其一）；
- PUT 更新处置（open→followed 状态机校验）；
- POST close 关闭闭环（followed→closed，记 closed_at + action_taken）；
- 业务失败返回 ApiResponse(code=400/404)（HTTP 200），与既有 API 约定一致。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    CloseFollowupRequest,
    OhFollowupCategory,
    OhFollowupCreate,
    OhFollowupResponse,
    OhFollowupStatus,
    OhFollowupUpdate,
)
from app.modules.safety.service import OhFollowupService

oh_followups_router = APIRouter()


@oh_followups_router.get(
    "/oh/followups", response_model=ApiResponse, summary="异常随访列表（到期排序）"
)
async def get_oh_followups(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: OhFollowupStatus | None = Query(None, description="随访状态（expired 为到期派生）"),
    category: OhFollowupCategory | None = Query(None, description="异常指标类别"),
    person_id: uuid.UUID | None = Query(None, description="人员 ID"),
    due_order: bool = Query(True, description="按到期日排序（过期优先）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """异常随访列表：状态/类别/人员筛选 + 到期排序；open 且超期记录派生展示为 expired"""
    service = OhFollowupService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_followups(
        skip=skip,
        limit=page_size,
        status=status.value if status else None,
        category=category.value if category else None,
        person_id=person_id,
        due_order=due_order,
    )
    return ApiResponse(
        data=[OhFollowupResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_followups_router.post(
    "/oh/followups", response_model=ApiResponse, summary="创建异常随访（手动补录）"
)
async def create_oh_followup(
    data: OhFollowupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动补录随访（source='manual'，status='open'，exam_id 或 person_id 必填其一）"""
    service = OhFollowupService(db)
    try:
        item = await service.create_followup(
            data, user_id=current_user.id if current_user else None
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))
    await db.commit()
    return ApiResponse(data=OhFollowupResponse.model_validate(item))


@oh_followups_router.put(
    "/oh/followups/{followup_id}", response_model=ApiResponse, summary="更新随访处置"
)
async def update_oh_followup(
    followup_id: uuid.UUID,
    data: OhFollowupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新随访（处置记录 action_taken → open 自动流转 followed；状态机校验）"""
    service = OhFollowupService(db)
    try:
        item = await service.update_followup(
            followup_id, data, user_id=current_user.id if current_user else None
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))
    if not item:
        return ApiResponse(code=404, message="随访记录不存在")
    await db.commit()
    return ApiResponse(data=OhFollowupResponse.model_validate(item))


@oh_followups_router.post(
    "/oh/followups/{followup_id}/close",
    response_model=ApiResponse,
    summary="关闭异常随访（闭环）",
)
async def close_oh_followup(
    followup_id: uuid.UUID,
    data: CloseFollowupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """关闭随访闭环：followed → closed，写 closed_at + action_taken"""
    service = OhFollowupService(db)
    try:
        item = await service.close_followup(
            followup_id,
            action_taken=data.action_taken,
            user_id=current_user.id if current_user else None,
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))
    if not item:
        return ApiResponse(code=404, message="随访记录不存在")
    await db.commit()
    return ApiResponse(data=OhFollowupResponse.model_validate(item))
