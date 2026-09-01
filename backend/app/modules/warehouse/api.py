"""Warehouse HTTP 路由：只做入参、依赖注入、调用 service、返回统一响应。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.warehouse import service
from app.modules.warehouse.schemas import (
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    MaterialCreate,
    MaterialResponse,
    MaterialUpdate,
    MovementCreate,
    MovementResponse,
    OverviewResponse,
    StockResponse,
    StocktakeCreate,
    StocktakeUpdate,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

router = create_module_router(MODULES_BY_CODE["warehouse"])


def _clean(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None


# ── 概览 ──


@router.get("/overview", summary="仓储概览统计")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    data = await service.get_overview(db)
    return success_response(OverviewResponse(**data).model_dump(mode="json"))


# ── 物料主数据 ──


@router.get("/materials", summary="物料主数据分页列表")
async def list_materials(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None, description="物料分类"),
    keyword: str | None = Query(default=None, description="编码/名称关键词"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:read")),
) -> JSONResponse:
    items, total = await service.list_materials(
        db, page=page, page_size=page_size, category=_clean(category), keyword=_clean(keyword)
    )
    data = [MaterialResponse.model_validate(m).model_dump(mode="json") for m in items]
    return paginated_response(data, page, page_size, total)


@router.post("/materials", status_code=201, summary="新增物料")
async def create_material(
    payload: MaterialCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:create")),
) -> JSONResponse:
    material = await service.create_material(db, payload, user)
    return success_response(
        MaterialResponse.model_validate(material).model_dump(mode="json"), status_code=201
    )


@router.put("/materials/{material_id}", summary="编辑物料")
async def update_material(
    material_id: UUID,
    payload: MaterialUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:update")),
) -> JSONResponse:
    material = await service.update_material(db, material_id, payload, user)
    return success_response(
        MaterialResponse.model_validate(material).model_dump(mode="json")
    )


@router.delete("/materials/{material_id}", summary="删除物料（软删除）")
async def delete_material(
    material_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:material:delete")),
) -> JSONResponse:
    await service.delete_material(db, material_id, user)
    return success_response(message="删除成功")


# ── 库位 ──


@router.get("/locations", summary="库位列表")
async def list_locations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:read")),
) -> JSONResponse:
    locations = await service.list_locations(db)
    data = [LocationResponse.model_validate(loc).model_dump(mode="json") for loc in locations]
    return success_response(data)


@router.post("/locations", status_code=201, summary="新增库位")
async def create_location(
    payload: LocationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:create")),
) -> JSONResponse:
    location = await service.create_location(db, payload, user)
    return success_response(
        LocationResponse.model_validate(location).model_dump(mode="json"), status_code=201
    )


@router.put("/locations/{location_id}", summary="编辑库位")
async def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:update")),
) -> JSONResponse:
    location = await service.update_location(db, location_id, payload, user)
    return success_response(
        LocationResponse.model_validate(location).model_dump(mode="json")
    )


@router.delete("/locations/{location_id}", summary="删除库位（软删除）")
async def delete_location(
    location_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:location:delete")),
) -> JSONResponse:
    await service.delete_location(db, location_id, user)
    return success_response(message="删除成功")


# ── 库存 ──


@router.get("/stocks", summary="现有库存分页列表")
async def list_stocks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None, description="物料分类"),
    keyword: str | None = Query(default=None, description="物料/批次关键词"),
    location_id: UUID | None = Query(default=None, description="库位ID"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> JSONResponse:
    items, total = await service.list_stocks(
        db,
        page=page,
        page_size=page_size,
        category=_clean(category),
        keyword=_clean(keyword),
        location_id=location_id,
    )
    data = [StockResponse.model_validate(s).model_dump(mode="json") for s in items]
    return paginated_response(data, page, page_size, total)


# ── 出入库 ──


@router.get("/movements", summary="出入库记录分页列表")
async def list_movements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    direction: str | None = Query(default=None, description="inbound/outbound/adjust"),
    source_type: str | None = Query(default=None, description="业务来源"),
    keyword: str | None = Query(default=None, description="单号/物料/批次关键词"),
    location_id: UUID | None = Query(default=None, description="库位ID"),
    occurred_from: datetime | None = Query(default=None, description="发生时间起"),
    occurred_to: datetime | None = Query(default=None, description="发生时间止"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:read")),
) -> JSONResponse:
    items, total = await service.list_movements(
        db,
        page=page,
        page_size=page_size,
        direction=_clean(direction),
        source_type=_clean(source_type),
        keyword=_clean(keyword),
        location_id=location_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    data = [MovementResponse.model_validate(m).model_dump(mode="json") for m in items]
    return paginated_response(data, page, page_size, total)


@router.post("/movements", status_code=201, summary="登记出入库")
async def create_movement(
    payload: MovementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    movement = await service.create_movement(db, payload, user)
    return success_response(
        MovementResponse.model_validate(movement).model_dump(mode="json"), status_code=201
    )


@router.delete("/movements/{movement_id}", summary="撤销出入库记录")
async def delete_movement(
    movement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:delete")),
) -> JSONResponse:
    await service.delete_movement(db, movement_id, user)
    return success_response(message="撤销成功")


# ── 盘点 ──


async def _stocktake_response(db: AsyncSession, stocktake_id: UUID) -> dict[str, Any]:
    return await service.build_stocktake_response(db, stocktake_id)


@router.get("/stocktakes", summary="盘点单分页列表")
async def list_stocktakes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, description="draft/confirmed"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:read")),
) -> JSONResponse:
    items, total = await service.list_stocktakes(
        db, page=page, page_size=page_size, status=_clean(status)
    )
    data = [await _stocktake_response(db, st.id) for st in items]
    return paginated_response(data, page, page_size, total)


@router.get("/stocktakes/{stocktake_id}", summary="盘点单详情")
async def get_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:read")),
) -> JSONResponse:
    return success_response(await _stocktake_response(db, stocktake_id))


@router.post("/stocktakes", status_code=201, summary="创建盘点单")
async def create_stocktake(
    payload: StocktakeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:create")),
) -> JSONResponse:
    stocktake = await service.create_stocktake(db, payload, user)
    return success_response(await _stocktake_response(db, stocktake.id), status_code=201)


@router.put("/stocktakes/{stocktake_id}", summary="填写盘点结果")
async def update_stocktake(
    stocktake_id: UUID,
    payload: StocktakeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:update")),
) -> JSONResponse:
    await service.update_stocktake(db, stocktake_id, payload, user)
    return success_response(await _stocktake_response(db, stocktake_id))


@router.post("/stocktakes/{stocktake_id}/confirm", summary="确认盘点单")
async def confirm_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:confirm")),
) -> JSONResponse:
    await service.confirm_stocktake(db, stocktake_id, user)
    return success_response(await _stocktake_response(db, stocktake_id))


@router.delete("/stocktakes/{stocktake_id}", summary="删除盘点单（仅草稿）")
async def delete_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:stocktake:delete")),
) -> JSONResponse:
    await service.delete_stocktake(db, stocktake_id, user)
    return success_response(message="删除成功")
