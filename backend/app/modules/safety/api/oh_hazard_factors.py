"""Safety API — oh_hazard_factors endpoints（危害因素 PPE 字典 + 标准枚举）。

对齐 backend-design.md §6.3：静态路径 /enums 先于任何动态路径。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import OhHazardFactorResponse
from app.modules.safety.service import OhHazardFactorService

oh_hazard_factors_router = APIRouter()


@oh_hazard_factors_router.get(
    "/oh/hazard-factors/enums", response_model=ApiResponse, summary="危害因素标准字典（42 项）"
)
async def get_oh_hazard_factor_enums(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """危害因素标准字典（42 项）"""
    service = OhHazardFactorService(db)
    enums = await service.get_enums()
    return ApiResponse(data=enums)


@oh_hazard_factors_router.get(
    "/oh/hazard-factors", response_model=ApiResponse, summary="危害因素 PPE 台账列表"
)
async def get_oh_hazard_factors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """危害因素 PPE 台账列表（分页）"""
    service = OhHazardFactorService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_factors(skip=skip, limit=page_size)
    return ApiResponse(
        data=[OhHazardFactorResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_hazard_factors_router.get(
    "/oh/hazard-factors/{factor_id}", response_model=ApiResponse, summary="危害因素字典项详情"
)
async def get_oh_hazard_factor(
    factor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """危害因素字典项详情"""
    service = OhHazardFactorService(db)
    item = await service.get_factor(factor_id)
    if not item:
        return ApiResponse(code=404, message="危害因素记录不存在")
    return ApiResponse(data=OhHazardFactorResponse.model_validate(item))
