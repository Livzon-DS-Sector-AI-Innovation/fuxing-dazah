"""Spare part repository functions."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
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
    department_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SparePart], int]:
    """获取备件列表（分页）"""
    query = select(SparePart).where(
        SparePart.is_deleted == False  # noqa: E712
    )

    # 数据范围过滤
    query = apply_equipment_scope(query, ctx, SparePart.department_id, "department_id")

    if category:
        query = query.where(SparePart.category == category)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            SparePart.code.ilike(pattern) | SparePart.name.ilike(pattern)
        )
    if is_active is not None:
        query = query.where(SparePart.is_active == is_active)
    if department_id:
        query = query.where(SparePart.department_id == department_id)

    count_query = select(func.count()).select_from(
        query.with_only_columns(SparePart.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(SparePart.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    spare_parts = list(result.scalars().all())

    # 批量查关联设备数和库存
    if spare_parts:
        ids = [sp.id for sp in spare_parts]
        # 关联设备数
        count_q = (
            select(
                EquipmentSparePart.spare_part_id,
                func.count().label("cnt"),
            )
            .where(
                EquipmentSparePart.spare_part_id.in_(ids),
                EquipmentSparePart.is_deleted == False,  # noqa: E712
            )
            .group_by(EquipmentSparePart.spare_part_id)
        )
        count_result = await db.execute(count_q)
        count_map = {row.spare_part_id: row.cnt for row in count_result}

        # 库存数据
        stock_q = (
            select(
                SparePartStock.spare_part_id,
                SparePartStock.current_qty,
                SparePartStock.safety_qty,
            )
            .where(
                SparePartStock.spare_part_id.in_(ids),
                SparePartStock.is_deleted == False,  # noqa: E712
            )
        )
        stock_result = await db.execute(stock_q)
        stock_map = {row.spare_part_id: (row.current_qty, row.safety_qty) for row in stock_result}

        for sp in spare_parts:
            sp.equipment_count = count_map.get(sp.id, 0)
            stock = stock_map.get(sp.id, (0, 0))
            sp.current_qty = stock[0]
            sp.min_qty = stock[1]

    return spare_parts, total


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


async def get_spare_part_by_code(
    db: AsyncSession,
    code: str,
) -> SparePart | None:
    """按备件编码查找未删除且启用的备件"""
    result = await db.execute(
        select(SparePart).where(
            SparePart.code == code,
            SparePart.is_deleted == False,  # noqa: E712
            SparePart.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


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
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(EquipmentSparePart)
        .options(selectinload(EquipmentSparePart.spare_part))
        .where(
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


async def get_spare_part_equipments(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> list[EquipmentSparePart]:
    """根据备件 ID 获取关联的设备列表"""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(EquipmentSparePart)
        .options(selectinload(EquipmentSparePart.equipment))
        .where(
            EquipmentSparePart.spare_part_id == spare_part_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_available_spare_parts(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> list[SparePart]:
    """获取某设备可用的备件：
    包含：无关联设备的备件（全局可用）OR 关联了该设备的备件
    排除：有关联但未关联此设备的备件
    """
    # 有关联设备的备件 ID 集合
    any_assoc = (
        select(EquipmentSparePart.spare_part_id)
        .where(EquipmentSparePart.is_deleted == False)  # noqa: E712
    )
    # 关联了此设备的备件 ID
    this_assoc = (
        select(EquipmentSparePart.spare_part_id)
        .where(
            EquipmentSparePart.equipment_id == equipment_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )

    query = (
        select(SparePart)
        .where(
            SparePart.is_deleted == False,  # noqa: E712
            SparePart.is_active == True,  # noqa: E712
            or_(
                SparePart.id.notin_(any_assoc),  # 无任何关联 → 全局可用
                SparePart.id.in_(this_assoc),     # 关联了此设备
            ),
        )
        .order_by(SparePart.code)
    )

    result = await db.execute(query)
    spare_parts = list(result.scalars().all())

    # 批量查库存
    if spare_parts:
        ids = [sp.id for sp in spare_parts]
        stock_q = (
            select(
                SparePartStock.spare_part_id,
                SparePartStock.current_qty,
            )
            .where(
                SparePartStock.spare_part_id.in_(ids),
                SparePartStock.is_deleted == False,  # noqa: E712
            )
        )
        stock_result = await db.execute(stock_q)
        stock_map = {row.spare_part_id: row.current_qty for row in stock_result}
        for sp in spare_parts:
            sp.current_qty = stock_map.get(sp.id, 0)

    return spare_parts


async def get_outbound_transactions(
    db: AsyncSession,
    ctx: "EquipmentAccessContext",  # noqa: F821
    page: int = 1,
    page_size: int = 20,
    transaction_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """获取库存流水（分页），支持按类型、备件名称筛选"""
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.work_order import WorkOrder

    base = (
        select(
            SparePartTransaction.id,
            SparePartTransaction.spare_part_id,
            SparePart.code.label("spare_part_code"),
            SparePart.name.label("spare_part_name"),
            SparePart.specification,
            SparePart.unit,
            SparePartTransaction.transaction_type,
            SparePartTransaction.quantity,
            SparePartTransaction.work_order_id,
            WorkOrder.work_order_no,
            Equipment.name.label("equipment_name"),
            SparePartTransaction.created_at.label("consumed_at"),
            SparePartTransaction.remark,
        )
        .join(SparePart, SparePart.id == SparePartTransaction.spare_part_id)
        .outerjoin(WorkOrder, WorkOrder.id == SparePartTransaction.work_order_id)
        .outerjoin(Equipment, Equipment.id == WorkOrder.equipment_id)
        .where(
            SparePartTransaction.is_deleted == False,  # noqa: E712
        )
    )

    if transaction_type:
        base = base.where(SparePartTransaction.transaction_type == transaction_type)
    else:
        base = base.where(SparePartTransaction.transaction_type.in_(["入库", "出库"]))

    if keyword:
        pattern = f"%{keyword}%"
        base = base.where(SparePart.name.ilike(pattern))

    # 数据范围过滤（按备件所属人）
    base = apply_equipment_scope(base, ctx, SparePart.created_by, "user_id")

    count_q = select(func.count()).select_from(base.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    data_q = base.order_by(SparePartTransaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(data_q)
    rows = [dict(row._mapping) for row in result]
    return rows, total


async def get_consumption_history_by_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询某设备历史上所有工单消耗的备件记录"""
    from app.modules.equipment.models.work_order import WorkOrder

    # 子查询：该设备的所有工单 ID
    wo_subq = (
        select(WorkOrder.id)
        .where(
            WorkOrder.equipment_id == equipment_id,
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )

    # 总量
    count_q = (
        select(func.count())
        .select_from(SparePartTransaction)
        .where(
            SparePartTransaction.work_order_id.in_(wo_subq),
            SparePartTransaction.transaction_type == "出库",
            SparePartTransaction.is_deleted == False,  # noqa: E712
        )
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # 分页数据
    data_q = (
        select(
            SparePartTransaction.id,
            SparePartTransaction.spare_part_id,
            SparePart.code.label("spare_part_code"),
            SparePart.name.label("spare_part_name"),
            SparePart.specification,
            SparePart.unit,
            SparePartTransaction.quantity,
            SparePartTransaction.work_order_id,
            WorkOrder.work_order_no,
            SparePartTransaction.created_at.label("consumed_at"),
            SparePartTransaction.remark,
        )
        .join(SparePart, SparePart.id == SparePartTransaction.spare_part_id)
        .join(WorkOrder, WorkOrder.id == SparePartTransaction.work_order_id)
        .where(
            SparePartTransaction.work_order_id.in_(wo_subq),
            SparePartTransaction.transaction_type == "出库",
            SparePartTransaction.is_deleted == False,  # noqa: E712
        )
        .order_by(SparePartTransaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(data_q)
    rows = [dict(row._mapping) for row in result]
    return rows, total
