"""Safety API — 四新域页面端点（3.0 四期 1-B）。

只读骨架：GET /safety/{goals|training-behavior|facilities|incidents} 返回
三态信封（not_connected / live / degraded）。四域当前未接入（连接位空）
是常态——不抛错不重试；接入后同端点直接出数，页面零改码。
字段口径见 docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md。
"""

from fastapi import APIRouter, Query

from app.modules.safety.schemas.domain_pages import DomainPageOut
from app.modules.safety.service.domain_pages import build_domain_page
from app.shared.schemas import ApiResponse

domain_pages_router = APIRouter()


async def _page(url_key: str, page: int, page_size: int) -> ApiResponse:
    data = await build_domain_page(url_key, page=page, page_size=page_size)
    return ApiResponse(data=DomainPageOut(**data).model_dump(mode="json"))


@domain_pages_router.get(
    "/goals",
    response_model=ApiResponse,
    summary="目标责任与绩效页面数据（三态信封）",
)
async def get_goals_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    return await _page("goals", page, page_size)


@domain_pages_router.get(
    "/training-behavior",
    response_model=ApiResponse,
    summary="教育培训与行为管控页面数据（三态信封）",
)
async def get_training_behavior_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    return await _page("training-behavior", page, page_size)


@domain_pages_router.get(
    "/facilities",
    response_model=ApiResponse,
    summary="设备设施管理页面数据（三态信封）",
)
async def get_facilities_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    return await _page("facilities", page, page_size)


@domain_pages_router.get(
    "/incidents",
    response_model=ApiResponse,
    summary="事故事件管理页面数据（三态信封）",
)
async def get_incidents_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    return await _page("incidents", page, page_size)
