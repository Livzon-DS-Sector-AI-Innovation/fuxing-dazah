"""Warehouse database queries. 只负责读写，不含业务规则。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStocktake,
    WarehouseStocktakeItem,
)

# ── 物料主数据 ──


async def list_materials(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None = None,
    keyword: str | None = None,
) -> tuple[list[WarehouseMaterial], int]:
    stmt = select(WarehouseMaterial).where(WarehouseMaterial.is_deleted == False)  # noqa: E712
    if category:
        stmt = stmt.where(WarehouseMaterial.category == category)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(WarehouseMaterial.code.ilike(like), WarehouseMaterial.name.ilike(like))
        )
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = stmt.order_by(WarehouseMaterial.code).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_material(db: AsyncSession, material_id: uuid.UUID) -> WarehouseMaterial | None:
    stmt = select(WarehouseMaterial).where(
        WarehouseMaterial.id == material_id,
        WarehouseMaterial.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_material_by_code(db: AsyncSession, code: str) -> WarehouseMaterial | None:
    stmt = select(WarehouseMaterial).where(
        WarehouseMaterial.code == code,
        WarehouseMaterial.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ── 库位 ──


async def list_locations(db: AsyncSession) -> list[WarehouseLocation]:
    stmt = (
        select(WarehouseLocation)
        .where(WarehouseLocation.is_deleted == False)  # noqa: E712
        .order_by(WarehouseLocation.code)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_location(db: AsyncSession, location_id: uuid.UUID) -> WarehouseLocation | None:
    stmt = select(WarehouseLocation).where(
        WarehouseLocation.id == location_id,
        WarehouseLocation.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_location_by_code(db: AsyncSession, code: str) -> WarehouseLocation | None:
    stmt = select(WarehouseLocation).where(
        WarehouseLocation.code == code,
        WarehouseLocation.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ── 库存 ──


async def list_stocks(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None = None,
    keyword: str | None = None,
    location_id: uuid.UUID | None = None,
) -> tuple[list[WarehouseStock], int]:
    stmt = select(WarehouseStock).where(WarehouseStock.is_deleted == False)  # noqa: E712
    if category:
        stmt = stmt.join(
            WarehouseMaterial,
            WarehouseStock.material_id == WarehouseMaterial.id,
        ).where(
            WarehouseMaterial.category == category,
            WarehouseMaterial.is_deleted == False,  # noqa: E712
        )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                WarehouseStock.material_code.ilike(like),
                WarehouseStock.material_name.ilike(like),
                WarehouseStock.batch_no.ilike(like),
            )
        )
    if location_id:
        stmt = stmt.where(WarehouseStock.location_id == location_id)
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = (
        stmt.order_by(WarehouseStock.material_code, WarehouseStock.batch_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), int(total or 0)


async def list_stocks_for_snapshot(
    db: AsyncSession,
    *,
    location_id: uuid.UUID | None = None,
) -> list[WarehouseStock]:
    """盘点快照用：返回范围内全部非删除库存（仅保留物料未删除的行）。"""
    stmt = (
        select(WarehouseStock)
        .join(WarehouseMaterial, WarehouseStock.material_id == WarehouseMaterial.id)
        .where(
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseMaterial.is_deleted == False,  # noqa: E712
        )
    )
    if location_id:
        stmt = stmt.where(WarehouseStock.location_id == location_id)
    stmt = stmt.order_by(WarehouseStock.material_code, WarehouseStock.batch_no)
    return list((await db.execute(stmt)).scalars().all())


async def get_stock_row(
    db: AsyncSession,
    *,
    material_id: uuid.UUID,
    batch_no: str,
    location_id: uuid.UUID,
) -> WarehouseStock | None:
    stmt = select(WarehouseStock).where(
        WarehouseStock.material_id == material_id,
        WarehouseStock.batch_no == batch_no,
        WarehouseStock.location_id == location_id,
        WarehouseStock.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_low_stock_materials(db: AsyncSession) -> list[tuple[str, Decimal, Decimal]]:
    """返回 (物料名称, 合计库存, 安全库存) 合计库存低于安全库存的物料。"""
    stmt = (
        select(
            WarehouseMaterial.name,
            func.coalesce(func.sum(WarehouseStock.quantity), Decimal("0")),
            WarehouseMaterial.safety_stock,
        )
        .join(WarehouseMaterial, WarehouseStock.material_id == WarehouseMaterial.id)
        .where(
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseMaterial.is_deleted == False,  # noqa: E712
            WarehouseMaterial.safety_stock > 0,
        )
        .group_by(WarehouseMaterial.id, WarehouseMaterial.name, WarehouseMaterial.safety_stock)
        .having(
            func.coalesce(func.sum(WarehouseStock.quantity), Decimal("0"))
            < WarehouseMaterial.safety_stock
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(str(r[0]), Decimal(str(r[1])), Decimal(str(r[2]))) for r in rows]


# ── 出入库 ──


async def list_movements(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    direction: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    location_id: uuid.UUID | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> tuple[list[WarehouseMovement], int]:
    stmt = select(WarehouseMovement).where(WarehouseMovement.is_deleted == False)  # noqa: E712
    if direction:
        stmt = stmt.where(WarehouseMovement.direction == direction)
    if source_type:
        stmt = stmt.where(WarehouseMovement.source_type == source_type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                WarehouseMovement.movement_no.ilike(like),
                WarehouseMovement.material_code.ilike(like),
                WarehouseMovement.material_name.ilike(like),
                WarehouseMovement.batch_no.ilike(like),
            )
        )
    if location_id:
        stmt = stmt.where(WarehouseMovement.location_id == location_id)
    if occurred_from:
        stmt = stmt.where(WarehouseMovement.occurred_at >= occurred_from)
    if occurred_to:
        stmt = stmt.where(WarehouseMovement.occurred_at < occurred_to)
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = (
        stmt.order_by(WarehouseMovement.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_movement(db: AsyncSession, movement_id: uuid.UUID) -> WarehouseMovement | None:
    stmt = select(WarehouseMovement).where(
        WarehouseMovement.id == movement_id,
        WarehouseMovement.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def sum_movements_quantity(
    db: AsyncSession,
    *,
    direction: str,
    occurred_from: datetime,
    occurred_to: datetime,
) -> Decimal:
    stmt = select(func.coalesce(func.sum(WarehouseMovement.quantity), Decimal("0"))).where(
        WarehouseMovement.is_deleted == False,  # noqa: E712
        WarehouseMovement.direction == direction,
        WarehouseMovement.occurred_at >= occurred_from,
        WarehouseMovement.occurred_at < occurred_to,
    )
    return Decimal(str(await db.scalar(stmt) or 0))


# ── 盘点 ──


async def list_stocktakes(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[WarehouseStocktake], int]:
    stmt = select(WarehouseStocktake).where(WarehouseStocktake.is_deleted == False)  # noqa: E712
    if status:
        stmt = stmt.where(WarehouseStocktake.status == status)
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = (
        stmt.order_by(WarehouseStocktake.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), int(total or 0)


async def get_stocktake(db: AsyncSession, stocktake_id: uuid.UUID) -> WarehouseStocktake | None:
    stmt = select(WarehouseStocktake).where(
        WarehouseStocktake.id == stocktake_id,
        WarehouseStocktake.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_stocktake_items(
    db: AsyncSession,
    stocktake_id: uuid.UUID,
) -> list[WarehouseStocktakeItem]:
    stmt = (
        select(WarehouseStocktakeItem)
        .where(
            WarehouseStocktakeItem.stocktake_id == stocktake_id,
            WarehouseStocktakeItem.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseStocktakeItem.material_code, WarehouseStocktakeItem.batch_no)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_stocktake_items_by_ids(
    db: AsyncSession,
    *,
    stocktake_id: uuid.UUID,
    item_ids: list[uuid.UUID],
) -> list[WarehouseStocktakeItem]:
    stmt = select(WarehouseStocktakeItem).where(
        WarehouseStocktakeItem.stocktake_id == stocktake_id,
        WarehouseStocktakeItem.id.in_(item_ids),
        WarehouseStocktakeItem.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars().all())


# ── 概览统计 ──


async def count_materials(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(WarehouseMaterial)
        .where(WarehouseMaterial.is_deleted == False)  # noqa: E712
    )
    return int(await db.scalar(stmt) or 0)


async def count_locations(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(WarehouseLocation)
        .where(WarehouseLocation.is_deleted == False)  # noqa: E712
    )
    return int(await db.scalar(stmt) or 0)


async def count_stock_skus(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(WarehouseStock)
        .where(
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseStock.quantity > 0,
        )
    )
    return int(await db.scalar(stmt) or 0)


async def exists_stock_for_material(db: AsyncSession, material_id: uuid.UUID) -> bool:
    stmt = (
        select(func.count())
        .select_from(WarehouseStock)
        .where(
            WarehouseStock.material_id == material_id,
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseStock.quantity > 0,
        )
    )
    return int(await db.scalar(stmt) or 0) > 0


async def exists_stock_in_location(db: AsyncSession, location_id: uuid.UUID) -> bool:
    stmt = (
        select(func.count())
        .select_from(WarehouseStock)
        .where(
            WarehouseStock.location_id == location_id,
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseStock.quantity > 0,
        )
    )
    return int(await db.scalar(stmt) or 0) > 0
