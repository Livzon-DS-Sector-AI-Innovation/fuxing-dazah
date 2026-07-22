"""Safety API — special_ops_personnel endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    SpecialOperationPersonnelCreate,
    SpecialOperationPersonnelResponse,
    SpecialOperationPersonnelUpdate,
)
from app.modules.safety.service import (
    SpecialOperationService,
)

special_ops_personnel_router = APIRouter()


@special_ops_personnel_router.get(
    "/special-operation-personnel",
    response_model=ApiResponse,
    summary="获取特殊作业人员资质列表",
)
async def get_special_operation_personnel(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    certificate_type: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业人员资质列表"""
    service = SpecialOperationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_personnel(
        skip, page_size, status, certificate_type, department, keyword
    )
    return ApiResponse(
        data=[SpecialOperationPersonnelResponse.model_validate(p) for p in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@special_ops_personnel_router.post(
    "/special-operation-personnel",
    response_model=ApiResponse,
    summary="创建特殊作业人员资质",
)
async def create_special_operation_personnel(
    data: SpecialOperationPersonnelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建特殊作业人员资质"""
    service = SpecialOperationService(db)
    item = await service.create_personnel(data)
    await db.commit()
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@special_ops_personnel_router.get(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="获取特殊作业人员资质详情",
)
async def get_special_operation_personnel_detail(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业人员资质详情"""
    service = SpecialOperationService(db)
    item = await service.get_personnel_by_id(personnel_id)
    if not item:
        return ApiResponse(code=404, message="人员资质不存在")
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@special_ops_personnel_router.put(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="更新特殊作业人员资质",
)
async def update_special_operation_personnel(
    personnel_id: uuid.UUID,
    data: SpecialOperationPersonnelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新特殊作业人员资质"""
    service = SpecialOperationService(db)
    item = await service.update_personnel(personnel_id, data)
    if not item:
        return ApiResponse(code=404, message="人员资质不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@special_ops_personnel_router.delete(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="删除特殊作业人员资质",
)
async def delete_special_operation_personnel(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除特殊作业人员资质"""
    service = SpecialOperationService(db)
    result = await service.delete_personnel(personnel_id)
    if not result:
        return ApiResponse(code=404, message="人员资质不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


