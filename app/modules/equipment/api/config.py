"""维护配置 API 路由."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.equipment import service
from app.modules.equipment.schemas import ClaimTimeoutUpdateRequest

router = APIRouter()


@router.get("/claim-timeout", summary="获取抢单超时配置")
async def get_claim_timeout(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    config = await service.get_claim_timeout_config(db)
    return success_response(data=config)


@router.put("/claim-timeout", summary="更新抢单超时配置")
async def update_claim_timeout(
    data: ClaimTimeoutUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    config = await service.update_claim_timeout_config(db, data)
    return success_response(data=config)
