"""Safety API — oh_positions endpoints（岗位危害因素台账）。

对齐 backend-design.md §6.3。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import OhHazardFactorsStatus, OhPositionResponse
from app.modules.safety.service import OhPositionService

oh_positions_router = APIRouter()


@oh_positions_router.get(
    "/oh/positions", response_model=ApiResponse, summary="岗位危害台账列表"
)
async def get_oh_positions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = Query(None, description="部门"),
    hazard_factors_status: OhHazardFactorsStatus | None = Query(
        None, description="危害因素状态: filled/empty/inferred"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """岗位危害台账列表（筛选 + 分页）"""
    service = OhPositionService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_positions(
        skip=skip,
        limit=page_size,
        department=department,
        hazard_factors_status=hazard_factors_status.value if hazard_factors_status else None,
    )
    return ApiResponse(
        data=[OhPositionResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_positions_router.get(
    "/oh/positions/{position_id}", response_model=ApiResponse, summary="岗位危害台账详情"
)
async def get_oh_position(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """岗位详情"""
    service = OhPositionService(db)
    item = await service.get_position(position_id)
    if not item:
        return ApiResponse(code=404, message="岗位记录不存在")
    return ApiResponse(data=OhPositionResponse.model_validate(item))
