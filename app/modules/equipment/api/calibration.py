"""校准管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
from app.modules.equipment.schemas import (
    CalibrationPlanCreate,
    CalibrationPlanResponse,
    CalibrationPlanUpdate,
    CalibrationRecordCreate,
    CalibrationRecordResponse,
)

router = APIRouter()


# ---------- 校准计划 ----------
@router.post("/plans", summary="新增校准计划")
async def create_calibration_plan(
    data: CalibrationPlanCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:create"),
    ),
) -> JSONResponse:
    plan = await service.create_calibration_plan(db, data, ctx)
    return success_response(data=CalibrationPlanResponse.model_validate(plan))


@router.get("/plans", summary="校准计划列表")
async def list_calibration_plans(
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    status: str | None = Query(None, description="状态"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plans, total = await service.get_calibration_plans(
        db, ctx=ctx, equipment_id=equipment_id, status=status,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[CalibrationPlanResponse.model_validate(p) for p in plans],
        page=page, page_size=page_size, total=total,
    )


@router.get("/plans/overdue", summary="查询到期/逾期的校准计划")
async def get_overdue_plans(
    days: int = Query(30, ge=1, description="提前天数"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plans = await service.get_overdue_calibration_plans(db, ctx, days)
    return success_response(
        data=[CalibrationPlanResponse.model_validate(p) for p in plans]
    )


@router.get("/plans/{plan_id}", summary="校准计划详情")
async def get_calibration_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    plan = await service.get_calibration_plan_by_id(db, plan_id)
    return success_response(data=CalibrationPlanResponse.model_validate(plan))


@router.put("/plans/{plan_id}", summary="修改校准计划")
async def update_calibration_plan(
    plan_id: uuid.UUID,
    data: CalibrationPlanUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    plan = await service.update_calibration_plan(db, plan_id, data, ctx)
    return success_response(data=CalibrationPlanResponse.model_validate(plan))


@router.delete("/plans/{plan_id}", summary="删除校准计划")
async def delete_calibration_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:delete"),
    ),
) -> JSONResponse:
    await service.delete_calibration_plan(db, plan_id, ctx)
    return success_response(message="删除成功")


# ---------- 校准记录 ----------
@router.post("/records", summary="新增校准记录")
async def create_calibration_record(
    data: CalibrationRecordCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:create"),
    ),
) -> JSONResponse:
    record = await service.create_calibration_record(db, data, ctx)
    return success_response(data=CalibrationRecordResponse.model_validate(record))


@router.get("/records", summary="校准记录列表")
async def list_calibration_records(
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    plan_id: uuid.UUID | None = Query(None, description="计划ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    records, total = await service.get_calibration_records(
        db, ctx=ctx, equipment_id=equipment_id, plan_id=plan_id,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[CalibrationRecordResponse.model_validate(r) for r in records],
        page=page, page_size=page_size, total=total,
    )


@router.get("/records/{record_id}", summary="校准记录详情")
async def get_calibration_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    record = await service.get_calibration_record_by_id(db, record_id)
    return success_response(data=CalibrationRecordResponse.model_validate(record))
