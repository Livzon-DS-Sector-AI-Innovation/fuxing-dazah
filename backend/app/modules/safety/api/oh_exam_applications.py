"""Safety API — oh_exam_applications endpoints（转岗离岗申请 + 差异分析）。

对齐 backend-design.md §6.4：静态路径（/stats）先于 /{id}。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    OhApplicationStatus,
    OhExamApplicationResponse,
    OhTransferType,
)
from app.modules.safety.service import OhTransferService

oh_exam_applications_router = APIRouter()


@oh_exam_applications_router.get(
    "/oh/applications", response_model=ApiResponse, summary="转岗离岗申请列表"
)
async def get_oh_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: OhApplicationStatus | None = Query(None, description="申请状态"),
    transfer_type: OhTransferType | None = Query(None, description="转岗/离岗"),
    keyword: str | None = Query(None, description="申请编号/姓名/部门关键词"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """转岗/离岗申请列表（状态/类型筛选 + 分页）"""
    service = OhTransferService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_applications(
        skip=skip,
        limit=page_size,
        status=status.value if status else None,
        transfer_type=transfer_type.value if transfer_type else None,
        keyword=keyword,
    )
    return ApiResponse(
        data=[OhExamApplicationResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_exam_applications_router.get(
    "/oh/applications/stats", response_model=ApiResponse, summary="转岗离岗申请统计"
)
async def get_oh_application_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """申请统计（total + 按状态分组 + 需体检数）"""
    service = OhTransferService(db)
    return ApiResponse(data=await service.get_stats())


@oh_exam_applications_router.get(
    "/oh/applications/{application_id}",
    response_model=ApiResponse,
    summary="转岗离岗申请详情（含差异分析结果）",
)
async def get_oh_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """申请详情（含 diff_analyze_result 展开）"""
    service = OhTransferService(db)
    item = await service.get_application(application_id)
    if not item or item.is_deleted:
        return ApiResponse(code=404, message="体检申请不存在")
    return ApiResponse(data=OhExamApplicationResponse.model_validate(item))


@oh_exam_applications_router.post(
    "/oh/applications/{application_id}/analyze",
    response_model=ApiResponse,
    summary="手动触发/重试转岗危害差异分析",
)
async def analyze_oh_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发/重试转岗危害差异分析（channel=web，失败可重试）"""
    service = OhTransferService(db)
    item = await service.analyze_transfer_diff(
        application_id,
        channel="web",
        user_id=current_user.id if current_user else None,
        user_name=current_user.name if current_user else None,
    )
    if not item:
        return ApiResponse(code=404, message="体检申请不存在")
    # UPDATE re-fetch 铁律：analyze 内多次 commit 后 updated_at（onupdate 列）处于
    # expired 状态，直接 model_validate 序列化访问会触发 MissingGreenlet，
    # 响应构造前显式 select 重新查询（对标 service/oh_health_exam.py）。
    item = await service.get_application(application_id)
    if not item:
        return ApiResponse(code=404, message="体检申请不存在")
    return ApiResponse(data=OhExamApplicationResponse.model_validate(item))
