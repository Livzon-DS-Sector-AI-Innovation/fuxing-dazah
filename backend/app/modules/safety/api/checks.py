"""Safety API — checks endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ConfirmCheckRequest,
    SafetyCheckCreate,
    SafetyCheckResponse,
    SafetyCheckUpdate,
)
from app.modules.safety.service import (
    SafetyService,
)

checks_router = APIRouter()


@checks_router.get("/checks", response_model=ApiResponse, summary="获取安全检查列表")
async def get_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    check_type: str | None = None,
    department: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全检查列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_checks(skip, page_size, status, check_type, department)
    return ApiResponse(
        data=[SafetyCheckResponse.model_validate(c) for c in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@checks_router.get("/checks/{check_id}", response_model=ApiResponse, summary="获取安全检查详情")
async def get_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全检查详情"""
    service = SafetyService(db)
    item = await service.get_check(check_id)
    if not item:
        return ApiResponse(code=404, message="检查记录不存在")
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.post("/checks", response_model=ApiResponse, summary="创建安全检查")
async def create_check(
    data: SafetyCheckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全检查"""
    service = SafetyService(db)
    item = await service.create_check(data)
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.put("/checks/{check_id}", response_model=ApiResponse, summary="更新安全检查")
async def update_check(
    check_id: uuid.UUID,
    data: SafetyCheckUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全检查"""
    service = SafetyService(db)
    item = await service.update_check(check_id, data)
    if not item:
        return ApiResponse(code=404, message="检查记录不存在")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.post("/checks/{check_id}/submit", response_model=ApiResponse, summary="提交安全检查")
async def submit_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交安全检查（草稿→已提交）"""
    service = SafetyService(db)
    item = await service.submit_check(check_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.post("/checks/{check_id}/review", response_model=ApiResponse, summary="审核安全检查")
async def review_check(
    check_id: uuid.UUID,
    result: str = Query(..., description="审核结果: qualified/unqualified"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审核安全检查"""
    service = SafetyService(db)
    item = await service.review_check(check_id, result)
    if not item:
        return ApiResponse(code=400, message="无法审核，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.post("/checks/{check_id}/confirm", response_model=ApiResponse, summary="确认检查")
async def confirm_check(
    check_id: uuid.UUID,
    data: ConfirmCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """确认安全检查（role=inspector 检查人员确认 / role=safety_officer 安全办确认）"""
    service = SafetyService(db)
    item = await service.confirm_check(check_id, data.role)
    if not item:
        return ApiResponse(code=400, message="确认失败")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@checks_router.delete("/checks/{check_id}", response_model=ApiResponse, summary="删除安全检查")
async def delete_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全检查"""
    service = SafetyService(db)
    result = await service.delete_check(check_id)
    if not result:
        return ApiResponse(code=404, message="检查记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


