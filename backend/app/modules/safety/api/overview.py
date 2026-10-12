"""Safety API — overview endpoints（总览驾驶舱，二期 3.0 门面）。

只读聚合：一个端点喂饱 /safety 驾驶舱（6 KPI + 速递回放 + 趋势 + 报警
分析 + 下钻三列 + 17 模块健康度）。service 层并行采集（各采集器独立
session）、单域失败降级。
"""

from fastapi import APIRouter

from app.modules.safety.schemas.overview import OverviewOut
from app.modules.safety.service.overview import build_overview
from app.shared.schemas import ApiResponse

overview_router = APIRouter()


@overview_router.get(
    "/overview",
    response_model=ApiResponse,
    summary="总览驾驶舱聚合数据（KPI/速递/趋势/下钻/健康度）",
)
async def get_overview() -> ApiResponse:
    """一次拉取喂饱驾驶舱；采集失败的单域置 None（errors 标注），整页仍 200。"""
    data = await build_overview()
    return ApiResponse(data=OverviewOut(**data).model_dump(mode="json"))
