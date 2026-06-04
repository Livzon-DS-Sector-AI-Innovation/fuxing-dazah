"""维护计划管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanResponse,
    MaintenancePlanUpdate,
)

router = APIRouter()


@router.post("/", summary="新增维护计划")
async def create_maintenance_plan(
    data: MaintenancePlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    plan = await service.create_maintenance_plan(db, data)
    return success_response(data=MaintenancePlanResponse.model_validate(plan))


@router.get("/", summary="维护计划列表")
async def list_maintenance_plans(
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    status: str | None = Query(None, description="状态"),
    keyword: str | None = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    plans, total = await service.get_maintenance_plans(
        db, equipment_id=equipment_id, status=status,
        keyword=keyword, page=page, page_size=page_size,
    )
    return paginated_response(
        data=[MaintenancePlanResponse.model_validate(p) for p in plans],
        page=page, page_size=page_size, total=total,
    )


@router.get("/overdue", summary="查询到期/逾期的维护计划")
async def get_overdue_plans(
    days: int = Query(30, ge=1, description="提前天数"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    plans = await service.get_overdue_maintenance_plans(db, days)
    return success_response(
        data=[MaintenancePlanResponse.model_validate(p) for p in plans]
    )


@router.get("/{plan_id}", summary="维护计划详情")
async def get_maintenance_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    plan = await service.get_maintenance_plan_by_id(db, plan_id)
    return success_response(data=MaintenancePlanResponse.model_validate(plan))


@router.put("/{plan_id}", summary="修改维护计划")
async def update_maintenance_plan(
    plan_id: uuid.UUID,
    data: MaintenancePlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    plan = await service.update_maintenance_plan(db, plan_id, data)
    return success_response(data=MaintenancePlanResponse.model_validate(plan))


@router.delete("/{plan_id}", summary="删除维护计划")
async def delete_maintenance_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    await service.delete_maintenance_plan(db, plan_id)
    return success_response(message="删除成功")
