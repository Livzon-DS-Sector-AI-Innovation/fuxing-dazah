"""Spare part repository functions."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.spare_part import (
    EquipmentSparePart,
    SparePart,
    SparePartStock,
    SparePartTransaction,
)
from app.modules.equipment.service.data_scope import apply_equipment_scope


async def create_spare_part(
    db: AsyncSession,
    data: dict[str, Any],
) -> SparePart:
    """创建备件"""
    spare_part = SparePart(**data)
    db.add(spare_part)
    await db.flush()
    await db.refresh(spare_part)
    return spare_part


async def get_spare_part_by_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePart | None:
    """根据ID获取备件"""
    result = await db.execute(
        select(SparePart).where(
            SparePart.id == spare_part_id,
            SparePart.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_spare_parts(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    category: str | None = None,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SparePart], int]:
    """获取备件列表（分页）"""
    query = select(SparePart).where(
        SparePart.is_deleted == False  # noqa: E712
    )

    # 数据范围过滤
    query = apply_equipment_scope(query, ctx, SparePart.created_by, "user_id")

    if category:
        query = query.where(SparePart.category == category)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            SparePart.code.ilike(pattern) | SparePart.name.ilike(pattern)
        )
    if is_active is not None:
        query = query.where(SparePart.is_active == is_active)

    count_query = select(func.count()).select_from(
        query.with_only_columns(SparePart.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(SparePart.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def exists_spare_part_by_code(
    db: AsyncSession,
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """检查备件编码是否已存在"""
    query = select(func.count()).select_from(SparePart).where(
        SparePart.code == code,
        SparePart.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(SparePart.id != exclude_id)
    result = await db.execute(query)
    return (result.scalar() or 0) > 0


async def update_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: dict[str, Any],
) -> SparePart | None:
    """更新备件"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if not spare_part:
        return None
    for key, value in data.items():
        setattr(spare_part, key, value)
    await db.flush()
    await db.refresh(spare_part)
    return spare_part


async def delete_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> bool:
    """删除备件（软删除）"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if not spare_part:
        return False
    spare_part.is_deleted = True
    await db.flush()
    return True


async def get_stock_by_spare_part_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePartStock | None:
    """根据备件ID获取库存记录"""
    result = await db.execute(
        select(SparePartStock).where(
            SparePartStock.spare_part_id == spare_part_id,
            SparePartStock.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def create_stock(
    db: AsyncSession,
    data: dict[str, Any],
) -> SparePartStock:
    """创建库存记录"""
    stock = SparePartStock(**data)
    db.add(stock)
    await db.flush()
    await db.refresh(stock)
    return stock


async def update_stock_qty(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    qty_change: int,
) -> SparePartStock | None:
    """更新库存数量"""
    stock = await get_stock_by_spare_part_id(db, spare_part_id)
    if not stock:
        return None
    stock.current_qty += qty_change
    await db.flush()
    await db.refresh(stock)
    return stock


async def create_transaction(
    db: AsyncSession,
    data: dict[str, Any],
) -> SparePartTransaction:
    """创建库存流水"""
    transaction = SparePartTransaction(**data)
    db.add(transaction)
    await db.flush()
    return transaction


async def get_stock_warnings(
    db: AsyncSession,
) -> list[tuple[SparePart, SparePartStock]]:
    """获取库存预警：当前库存 < 安全库存"""
    result = await db.execute(
        select(SparePart, SparePartStock)
        .join(SparePartStock, SparePartStock.spare_part_id == SparePart.id)
        .where(
            SparePart.is_deleted == False,  # noqa: E712
            SparePartStock.is_deleted == False,  # noqa: E712
            SparePartStock.current_qty < SparePartStock.safety_qty,
            SparePartStock.safety_qty > 0,
        )
    )
    return list(result.all())


async def create_equipment_spare_part(
    db: AsyncSession,
    data: dict[str, Any],
) -> EquipmentSparePart:
    """创建设备-备件关联"""
    link = EquipmentSparePart(**data)
    db.add(link)
    await db.flush()
    await db.refresh(link)
    return link


async def get_equipment_spare_parts(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> list[EquipmentSparePart]:
    """获取设备的备件列表"""
    result = await db.execute(
        select(EquipmentSparePart).where(
            EquipmentSparePart.equipment_id == equipment_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def delete_equipment_spare_part(
    db: AsyncSession,
    link_id: uuid.UUID,
) -> bool:
    """删除设备-备件关联（软删除）"""
    result = await db.execute(
        select(EquipmentSparePart).where(
            EquipmentSparePart.id == link_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        return False
    link.is_deleted = True
    await db.flush()
    return True
