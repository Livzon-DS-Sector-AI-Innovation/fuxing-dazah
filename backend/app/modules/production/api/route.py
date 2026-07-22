"""工艺路线 API — 只做 HTTP 层。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import RouteCreate, RouteGraphIn, RouteOut
from app.modules.production.service import route_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_manage = require_permission("production:process:manage")
_read = require_permission("production:batch:read")


@router.get("/routes", summary="工艺路线列表")
async def list_routes(
    product_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await route_service.list_routes_paged(db, product_id, page, page_size)
    return paginated_response(
        [RouteOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/routes", summary="新建工艺路线（draft）")
async def create_route(
    payload: RouteCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.create_route(db, payload, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.get("/routes/{route_id}", summary="工艺路线完整图")
async def get_route_graph(
    route_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    graph = await route_service.get_graph(db, route_id)
    return success_response(graph.model_dump(mode="json"))


@router.put("/routes/{route_id}/graph", summary="整图保存（仅 draft）")
async def save_route_graph(
    route_id: uuid.UUID,
    payload: RouteGraphIn,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.save_graph(db, route_id, payload, user)
    return success_response()


@router.post("/routes/{route_id}/publish", summary="发布路线")
async def publish_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.publish_route(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.post("/routes/{route_id}/archive", summary="归档路线")
async def archive_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.archive_route(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.post("/routes/{route_id}/new-version", summary="复制新版本（draft）")
async def new_route_version(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.new_version(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.delete("/routes/{route_id}", summary="删除路线（仅 draft）")
async def delete_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.delete_route(db, route_id, user)
    return success_response()
