"""Safety API — facility_map endpoints（3.x 平台关联 F2）。

GET /safety/facility-map/pins?date=：当日特殊作业票（平台 createTime 口径）
+ 今日消防/中控报警，经 location_district_map 匹配后按分区聚合 + 未映射
清单。分区轮廓不走接口（前端静态资产）；单路数据源失败降级进 errors。
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.schemas.facility_map import FacilityMapPinsOut
from app.modules.safety.service.facility_map.service import (
    bj_today,
    open_pins_service,
)
from app.shared.schemas import ApiResponse

facility_map_router = APIRouter()


@facility_map_router.get(
    "/facility-map/pins",
    response_model=ApiResponse,
    summary="厂区风险分区当日分布 pins（作业票+报警按分区聚合）",
)
async def get_facility_map_pins(
    date: date_type | None = Query(None, description="YYYY-MM-DD，缺省北京时间今日"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    target = date or bj_today()
    payload = await open_pins_service(session=db).get_pins(target)
    return ApiResponse(
        data=FacilityMapPinsOut(**payload).model_dump(mode="json"),
        meta={"source": "tiji-platform+bitable", "mode": "direct"},
    )
