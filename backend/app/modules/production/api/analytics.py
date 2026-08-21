"""生产分析 API 路由。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.production.schemas.analytics import StepCycleResponse
from app.modules.production.service.analytics_service import (
    get_field_trend,
    get_stage_summary,
    get_step_cycle_analytics,
)
from app.platform.identity.deps import User, get_current_user
from app.platform.permission.deps import require_permission

router = APIRouter()

_read = require_permission("production:batch:read")


@router.get(
    "/analytics/step-cycle",
    response_model=StepCycleResponse,
    summary="工序周期分析",
    description="按路线/产品/时间范围聚合各工序的执行耗时，以小时为单位。仅统计首次执行。",
)
async def step_cycle(
    route_id: uuid.UUID | None = Query(None, description="工艺路线 ID"),
    product_id: uuid.UUID | None = Query(None, description="产品 ID"),
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天，默认 30"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> JSONResponse:
    result = await get_step_cycle_analytics(
        db, route_id=route_id, product_id=product_id, days=days,
    )
    return success_response(data=result.model_dump())


@router.get("/analytics/field-trend", summary="字段趋势（跨批次时间序列）")
async def field_trend(
    route_id: uuid.UUID,
    node_code: str = Query(..., max_length=50),
    field_key: str = Query(..., max_length=50),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = await get_field_trend(db, route_id, node_code, field_key)
    return success_response(rows)


@router.get("/analytics/stage-summary", summary="工段汇总平铺矩阵")
async def stage_summary(
    stage_name: str | None = Query(default=None, max_length=100),
    route_id: uuid.UUID | None = None,
    view_all: bool = Query(default=False),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await get_stage_summary(db, stage_name, route_id, user.id, view_all)
    return success_response(out.model_dump(mode="json"))
