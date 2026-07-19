"""产品 API — 只做 HTTP 层。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import ProductCreate, ProductOut, ProductUpdate
from app.modules.production.service import route_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_manage = require_permission("production:process:manage")
_read = require_permission("production:batch:read")


@router.get("/products", summary="产品列表")
async def list_products(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await route_service.list_products_paged(db, keyword, page, page_size)
    return paginated_response(
        [ProductOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/products", summary="新建产品")
async def create_product(
    payload: ProductCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.create_product(db, payload, user)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.get("/products/{product_id}", summary="产品详情")
async def get_product(
    product_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.get_product_or_404(db, product_id)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.put("/products/{product_id}", summary="更新产品")
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.update_product(db, product_id, payload, user)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.delete("/products/{product_id}", summary="删除产品")
async def delete_product(
    product_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.delete_product(db, product_id, user)
    return success_response()
