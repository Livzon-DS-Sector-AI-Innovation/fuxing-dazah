"""Spare part service: business logic for spare parts and stock."""

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.spare_part import (
    SparePart,
    SparePartStock,
)
from app.modules.equipment.schemas.spare_part import (
    SparePartCreate,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockWarningResponse,
)
from app.modules.equipment.service.data_scope import verify_write_ownership


async def create_spare_part(
    db: AsyncSession,
    data: SparePartCreate,
) -> SparePart:
    """创建备件，自动创建库存记录"""
    if await repo.exists_spare_part_by_code(db, data.code):
        raise DuplicateException("备件编码", data.code)

    spare_part = await repo.create_spare_part(db, data.model_dump())

    await repo.create_stock(db, {"spare_part_id": spare_part.id})

    return spare_part


async def get_spare_part_by_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePart:
    """获取备件"""
    spare_part = await repo.get_spare_part_by_id(db, spare_part_id)
    if not spare_part:
        raise NotFoundException("备件", str(spare_part_id))
    return spare_part


async def get_spare_parts(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    category: str | None = None,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SparePart], int]:
    """获取备件列表"""
    return await repo.get_spare_parts(
        db,
        ctx,
        category=category,
        keyword=keyword,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )


async def update_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: SparePartUpdate,
    ctx: EquipmentAccessContext,
) -> SparePart:
    """更新备件"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "created_by", "user_id")

    update_data = data.model_dump(exclude_unset=True)

    if "code" in update_data:
        code_exists = await repo.exists_spare_part_by_code(
            db, update_data["code"], exclude_id=spare_part_id
        )
        if code_exists:
            raise DuplicateException("备件编码", update_data["code"])

    result = await repo.update_spare_part(db, spare_part_id, update_data)
    if not result:
        raise NotFoundException("备件", str(spare_part_id))
    return result


async def delete_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> bool:
    """删除备件"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    await verify_write_ownership(ctx, spare_part, "created_by", "user_id")
    return await repo.delete_spare_part(db, spare_part_id)


async def get_stock_by_spare_part_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePartStock:
    """获取库存记录"""
    stock = await repo.get_stock_by_spare_part_id(db, spare_part_id)
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))
    return stock


async def inbound_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockInboundRequest,
    ctx: EquipmentAccessContext | None = None,
) -> SparePartStock:
    """入库"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if ctx:
        await verify_write_ownership(ctx, spare_part, "created_by", "user_id")

    stock = await repo.update_stock_qty(db, spare_part_id, data.quantity)
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))

    if data.warehouse_location is not None:
        stock.warehouse_location = data.warehouse_location

    await repo.create_transaction(
        db,
        {
            "spare_part_id": spare_part_id,
            "transaction_type": "入库",
            "quantity": data.quantity,
            "remark": data.remark,
        },
    )

    await db.flush()
    await db.refresh(stock)
    return stock


async def outbound_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    quantity: int,
) -> SparePartStock:
    """出库（内部使用）"""
    stock = await get_stock_by_spare_part_id(db, spare_part_id)

    if stock.current_qty < quantity:
        raise AppException(
            message=f"库存不足，当前库存 {stock.current_qty}，出库数量 {quantity}"
        )

    stock = cast(SparePartStock, await repo.update_stock_qty(db, spare_part_id, -quantity))
    if not stock:
        raise NotFoundException("库存记录", str(spare_part_id))

    await repo.create_transaction(
        db,
        {
            "spare_part_id": spare_part_id,
            "transaction_type": "出库",
            "quantity": -quantity,
        },
    )

    await db.flush()
    await db.refresh(stock)
    return stock


async def adjust_stock(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    data: StockAdjustRequest,
    ctx: EquipmentAccessContext | None = None,
) -> SparePartStock:
    """盘点调整"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if ctx:
        await verify_write_ownership(ctx, spare_part, "created_by", "user_id")

    stock = await get_stock_by_spare_part_id(db, spare_part_id)

    diff = data.new_qty - stock.current_qty

    if diff != 0:
        stock = cast(SparePartStock, await repo.update_stock_qty(db, spare_part_id, diff))
        if not stock:
            raise NotFoundException("库存记录", str(spare_part_id))

        await repo.create_transaction(
            db,
            {
                "spare_part_id": spare_part_id,
                "transaction_type": "盘点调整",
                "quantity": diff,
                "remark": data.remark,
            },
        )

    await db.flush()
    await db.refresh(stock)
    return stock


async def get_stock_warnings(
    db: AsyncSession,
) -> list[StockWarningResponse]:
    """获取库存预警"""
    warnings = await repo.get_stock_warnings(db)
    result = []
    for spare_part, stock in warnings:
        result.append(
            StockWarningResponse(
                spare_part=spare_part,  # pyright: ignore[reportArgumentType]
                stock=stock,  # pyright: ignore[reportArgumentType]
                shortage=stock.safety_qty - stock.current_qty,
            )
        )
    return result
