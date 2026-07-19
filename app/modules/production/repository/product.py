"""产品数据查询。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Product

__all__ = [
    "get_product",
    "get_product_by_name",
    "get_products_by_ids",
    "list_products",
]


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    stmt = select(Product).where(Product.id == product_id, Product.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_product_by_name(db: AsyncSession, name: str) -> Product | None:
    stmt = select(Product).where(
        Product.product_name == name, Product.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_products(
    db: AsyncSession, keyword: str | None, page: int, page_size: int
) -> tuple[list[Product], int]:
    stmt = select(Product).where(Product.is_deleted == False)  # noqa: E712
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            Product.product_code.ilike(pattern) | Product.product_name.ilike(pattern)
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(Product.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def get_products_by_ids(
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[Product]:
    """按 ID 批量查询产品。"""
    if not ids:
        return []
    stmt = select(Product).where(
        Product.id.in_(ids),
        Product.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
