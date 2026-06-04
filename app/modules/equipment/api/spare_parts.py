"""备件管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.schemas import (
    SparePartCreate,
    SparePartResponse,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockResponse,
    StockWarningResponse,
)

router = APIRouter()


@router.post("/", summary="创建备件")
async def create_spare_part(
    data: SparePartCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    spare_part = await service.create_spare_part(db, data)
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.get("/", summary="备件列表")
async def list_spare_parts(
    category: str | None = Query(None, description="备件分类"),
    keyword: str | None = Query(None, description="关键词搜索"),
    is_active: bool | None = Query(None, description="是否启用"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    spare_parts, total = await service.get_spare_parts(
        db, category=category, keyword=keyword,
        is_active=is_active, page=page, page_size=page_size,
    )
    return paginated_response(
        data=[SparePartResponse.model_validate(sp) for sp in spare_parts],
        page=page, page_size=page_size, total=total,
    )


@router.get("/stock/warnings", summary="库存预警列表")
async def get_stock_warnings(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    warnings = await service.get_stock_warnings(db)
    return success_response(
        data=[
            StockWarningResponse(
                spare_part=SparePartResponse.model_validate(w["spare_part"]),
                stock=StockResponse.model_validate(w["stock"]),
                shortage=w["shortage"],
            )
            for w in warnings
        ]
    )


@router.get("/{spare_part_id}", summary="备件详情")
async def get_spare_part(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    spare_part = await service.get_spare_part_by_id(db, spare_part_id)
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.put("/{spare_part_id}", summary="更新备件")
async def update_spare_part(
    spare_part_id: uuid.UUID,
    data: SparePartUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    spare_part = await service.update_spare_part(db, spare_part_id, data)
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.delete("/{spare_part_id}", summary="删除备件")
async def delete_spare_part(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    await service.delete_spare_part(db, spare_part_id)
    return success_response(message="删除成功")


@router.get("/{spare_part_id}/stock", summary="查看库存")
async def get_stock(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stock = await service.get_stock_by_spare_part_id(db, spare_part_id)
    return success_response(data=StockResponse.model_validate(stock))


@router.post("/{spare_part_id}/stock/inbound", summary="入库")
async def inbound_stock(
    spare_part_id: uuid.UUID,
    data: StockInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    stock = await service.inbound_stock(db, spare_part_id, data)
    return success_response(data=StockResponse.model_validate(stock))


@router.post("/{spare_part_id}/stock/adjust", summary="盘点调整")
async def adjust_stock(
    spare_part_id: uuid.UUID,
    data: StockAdjustRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    stock = await service.adjust_stock(db, spare_part_id, data)
    return success_response(data=StockResponse.model_validate(stock))
