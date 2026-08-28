"""Meter 全局设置 API 端点。"""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.meter import service
from app.modules.meter.api._router import router
from app.modules.meter.schemas import MeterSettingsResponse, MeterSettingsUpdate

# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════


@router.get("/settings", summary="获取全局设置（提醒时间）")
async def get_settings(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await service.get_meter_settings(db)
    return success_response(MeterSettingsResponse(**result).model_dump(mode="json"))



@router.put("/settings", summary="更新全局设置（提醒时间）")
async def update_settings(
    data: MeterSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        result = await service.update_meter_settings(db, data.notify_time)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"code": 400, "message": str(e)},
        )
    await db.commit()
    return success_response(MeterSettingsResponse(**result).model_dump(mode="json"))
