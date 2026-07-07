"""维护配置 API 路由."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
from app.modules.equipment.schemas import (
    AdvanceDaysUpdateRequest,
    ClaimTimeoutUpdateRequest,
)

router = APIRouter()


@router.get("/claim-timeout", summary="获取抢单超时配置")
async def get_claim_timeout(
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    config = await service.get_claim_timeout_config(db)
    return success_response(data=config)


@router.put("/claim-timeout", summary="更新抢单超时配置")
async def update_claim_timeout(
    data: ClaimTimeoutUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    config = await service.update_claim_timeout_config(db, data)
    return success_response(data=config)


@router.get("/advance-days", summary="获取维护计划提前创建天数")
async def get_advance_days(
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    config = await service.get_advance_days_config(db)
    return success_response(data=config)


@router.put("/advance-days", summary="更新维护计划提前创建天数")
async def update_advance_days(
    data: AdvanceDaysUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    config = await service.update_advance_days_config(db, data)
    return success_response(data=config)
