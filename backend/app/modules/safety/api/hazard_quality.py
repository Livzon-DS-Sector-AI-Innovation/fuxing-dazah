"""P1-4 D2 —— 隐患 AI 识别质量看板只读 API。

``GET /hazard-quality/dashboard?days=30|7``：实时聚合（service 层
``build_quality_dashboard``，指标与离线 replay 同口径，spec §4.2）。
鉴权沿安全域前例（subsidy 同款可选鉴权，token 缺省放行）；无写路径。

P1-3 追加：``GET /hazard-quality/exception-reviews?days=30|7``——例外复核
Tab（observe 口径指标 + 复核清单）；既有 dashboard 端点行为不变。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.service.hazard_direct.quality_dashboard import (
    ALLOWED_WINDOWS,
    build_exception_review_dashboard,
    build_quality_dashboard,
)
from app.shared.schemas import ApiResponse

hazard_quality_router = APIRouter()


@hazard_quality_router.get(
    "/hazard-quality/dashboard",
    response_model=ApiResponse,
    summary="隐患 AI 识别质量看板（实时聚合，与 replay 同口径）",
)
async def get_hazard_quality_dashboard(
    days: int = Query(30, description="时间窗（天），仅支持 7 / 30"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    if days not in ALLOWED_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"days 仅支持 {list(ALLOWED_WINDOWS)}，当前 {days}",
        )
    data = await build_quality_dashboard(db, days=days)
    return ApiResponse(data=data)


@hazard_quality_router.get(
    "/hazard-quality/exception-reviews",
    response_model=ApiResponse,
    summary="隐患 AI 识别例外复核 Tab（P1-3 observe：例外率/rescued率/清单）",
)
async def get_exception_review_dashboard(
    days: int = Query(30, description="时间窗（天），仅支持 7 / 30"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    if days not in ALLOWED_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"days 仅支持 {list(ALLOWED_WINDOWS)}，当前 {days}",
        )
    data = await build_exception_review_dashboard(db, days=days)
    return ApiResponse(data=data)
