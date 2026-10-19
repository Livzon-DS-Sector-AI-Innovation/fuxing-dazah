"""Spare part repository functions."""

import json
import uuid
from datetime import datetime
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
    low_stock: bool | None = None,
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
    if low_stock is not None:
        low_stock_exists = (
            select(SparePartStock.id)
            .where(
                SparePartStock.spare_part_id == SparePart.id,
                SparePartStock.is_deleted == False,  # noqa: E712
                SparePartStock.safety_qty > 0,
                SparePartStock.current_qty < SparePartStock.safety_qty,
            )
            .exists()
        )
        query = query.where(low_stock_exists if low_stock else ~low_stock_exists)
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
            select(SparePartStock)
            .where(
                SparePartStock.spare_part_id.in_(ids),
                SparePartStock.is_deleted == False,  # noqa: E712
            )
        )
        stock_result = await db.execute(stock_q)
        stock_map = {stock.spare_part_id: stock for stock in stock_result.scalars()}

        # 待验收工单占用量（可用 = current - reserved）
        reserved_map = await get_reserved_quantities(db, ids)

        for sp in spare_parts:
            sp.equipment_count = count_map.get(sp.id, 0)
            stock = stock_map.get(sp.id)
            sp.current_qty = stock.current_qty if stock else 0
            sp.min_qty = stock.safety_qty if stock else 0
            sp.safety_qty = stock.safety_qty if stock else 0  # type: ignore[attr-defined]
            sp.min_order_qty = stock.min_order_qty if stock else 1  # type: ignore[attr-defined]
            sp.warehouse_location = stock.warehouse_location if stock else None  # type: ignore[attr-defined]
            sp.is_low_stock = bool(  # type: ignore[attr-defined]
                stock
                and stock.safety_qty > 0
                and stock.current_qty < stock.safety_qty
            )
            sp.reserved_qty = reserved_map.get(sp.id, 0)  # type: ignore[attr-defined]

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
    for_update: bool = False,
) -> SparePartStock | None:
    """根据备件ID获取库存记录。

    for_update=True 时对库存行加锁，供「先校验后增减」的写路径使用，
    避免并发下两个请求都读到旧值、各自写回导致丢更新。
    """
    stmt = select(SparePartStock).where(
        SparePartStock.spare_part_id == spare_part_id,
        SparePartStock.is_deleted == False,  # noqa: E712
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_stock(
    db: AsyncSession,
    data: dict[str, Any],
) -> SparePartStock:
    """创建库存记录"""
    stock = SparePartStock(**data)
    db.add(stock)
    await db.flush()
    return stock


async def update_stock_qty(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
    qty_change: int,
) -> SparePartStock | None:
    """更新库存数量（行锁内自增，调用方未见库存行时返回 None）"""
    stock = await get_stock_by_spare_part_id(db, spare_part_id, for_update=True)
    if not stock:
        return None
    stock.current_qty += qty_change
    await db.flush()
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
    ctx: EquipmentAccessContext,
) -> list[tuple[SparePart, SparePartStock]]:
    """获取库存预警：当前库存 < 安全库存（按备件归属部门过滤）"""
    query = (
        select(SparePart, SparePartStock)
        .join(SparePartStock, SparePartStock.spare_part_id == SparePart.id)
        .where(
            SparePart.is_deleted == False,  # noqa: E712
            SparePartStock.is_deleted == False,  # noqa: E712
            SparePartStock.current_qty < SparePartStock.safety_qty,
            SparePartStock.safety_qty > 0,
        )
    )
    scoped = apply_equipment_scope(query, ctx, SparePart.department_id, "department_id")
    result = await db.execute(scoped)
    return [(spare_part, stock) for spare_part, stock in result.all()]


async def create_equipment_spare_part(
    db: AsyncSession,
    data: dict[str, Any],
) -> EquipmentSparePart:
    """创建设备-备件关联"""
    link = EquipmentSparePart(**data)
    db.add(link)
    await db.flush()
    return link


async def get_equipment_spare_parts(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> list[EquipmentSparePart]:
    """获取设备的备件列表（排除已软删的备件）"""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(EquipmentSparePart)
        .options(selectinload(EquipmentSparePart.spare_part))
        .join(SparePart, SparePart.id == EquipmentSparePart.spare_part_id)
        .where(
            EquipmentSparePart.equipment_id == equipment_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
            SparePart.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def delete_equipment_spare_parts_by_spare_part(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> int:
    """软删某备件的全部设备关联（删除备件时级联清理）"""
    result = await db.execute(
        select(EquipmentSparePart).where(
            EquipmentSparePart.spare_part_id == spare_part_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    links = list(result.scalars().all())
    for link in links:
        link.is_deleted = True
    await db.flush()
    return len(links)


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
    """根据备件 ID 获取关联的设备列表（排除已软删的备件）"""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(EquipmentSparePart)
        .options(selectinload(EquipmentSparePart.equipment))
        .join(SparePart, SparePart.id == EquipmentSparePart.spare_part_id)
        .where(
            EquipmentSparePart.spare_part_id == spare_part_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
            SparePart.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_available_spare_parts(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    ctx: EquipmentAccessContext | None = None,
    keyword: str | None = None,
    limit: int = 200,
) -> list[SparePart]:
    """获取某设备可用的备件：
    包含：无关联设备的备件（全局可用）OR 关联了该设备的备件
    排除：有关联但未关联此设备的备件
    附带 is_linked / required_qty（供工单领料分组与默认数量）
    """
    # 有关联设备的备件 ID 集合
    any_assoc = (
        select(EquipmentSparePart.spare_part_id)
        .where(EquipmentSparePart.is_deleted == False)  # noqa: E712
    )
    # 关联了此设备的（备件 ID, 需求数量）
    this_assoc_q = (
        select(
            EquipmentSparePart.spare_part_id,
            EquipmentSparePart.quantity,
        )
        .where(
            EquipmentSparePart.equipment_id == equipment_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    this_assoc_result = await db.execute(this_assoc_q)
    this_assoc: dict[uuid.UUID, int] = {
        row.spare_part_id: row.quantity for row in this_assoc_result
    }

    query = (
        select(SparePart)
        .where(
            SparePart.is_deleted == False,  # noqa: E712
            SparePart.is_active == True,  # noqa: E712
            or_(
                SparePart.id.notin_(any_assoc),  # 无任何关联 → 全局可用
                SparePart.id.in_(this_assoc.keys()),  # 关联了此设备
            ),
        )
        .order_by(SparePart.code)
        .limit(limit)
    )

    # 数据范围过滤与列表口径一致（此前完全不过滤，可枚举全公司备件）。
    # 历史无归属部门（department_id IS NULL）的备件沿用详情读校验的放行口径，
    # 否则升级前由超管建档的备件会从工单领料选择中消失。
    if ctx is not None and not ctx.is_unrestricted:
        dept_filter = SparePart.department_id.is_(None)
        if ctx.visible_department_ids:
            dept_filter = or_(
                SparePart.department_id.in_(ctx.visible_department_ids),
                dept_filter,
            )
        query = query.where(dept_filter)

    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            SparePart.code.ilike(pattern) | SparePart.name.ilike(pattern)
        )

    result = await db.execute(query)
    spare_parts = list(result.scalars().all())

    # 批量查库存（含安全库存，供前端标红低库存选项）
    if spare_parts:
        ids = [sp.id for sp in spare_parts]
        stock_q = (
            select(SparePartStock)
            .where(
                SparePartStock.spare_part_id.in_(ids),
                SparePartStock.is_deleted == False,  # noqa: E712
            )
        )
        stock_result = await db.execute(stock_q)
        stock_map = {s.spare_part_id: s for s in stock_result.scalars()}
        for sp in spare_parts:
            stock = stock_map.get(sp.id)
            sp.current_qty = stock.current_qty if stock else 0
            sp.safety_qty = stock.safety_qty if stock else 0  # type: ignore[attr-defined]
            sp.is_low_stock = bool(  # type: ignore[attr-defined]
                stock
                and stock.safety_qty > 0
                and stock.current_qty < stock.safety_qty
            )
            sp.is_linked = sp.id in this_assoc  # type: ignore[attr-defined]
            sp.required_qty = this_assoc.get(sp.id, 1)  # type: ignore[attr-defined]

    return spare_parts


async def get_outbound_transactions(
    db: AsyncSession,
    ctx: "EquipmentAccessContext",  # noqa: F821
    page: int = 1,
    page_size: int = 20,
    transaction_type: str | None = None,
    keyword: str | None = None,
    spare_part_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """获取库存流水（分页），支持按类型、备件、日期区间、关键字筛选。

    数据范围按备件归属部门过滤（与备件列表同口径；此前按 created_by
    过滤会导致同部门用户看得到备件却查不到别人的流水）。
    """
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.work_order import WorkOrder
    from app.platform.identity.models import User

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
            User.name.label("operator_name"),
            SparePartTransaction.created_at.label("consumed_at"),
            SparePartTransaction.remark,
        )
        .join(SparePart, SparePart.id == SparePartTransaction.spare_part_id)
        .outerjoin(WorkOrder, WorkOrder.id == SparePartTransaction.work_order_id)
        .outerjoin(Equipment, Equipment.id == WorkOrder.equipment_id)
        .outerjoin(User, User.id == SparePartTransaction.created_by)
        .where(
            SparePartTransaction.is_deleted == False,  # noqa: E712
        )
    )

    if transaction_type:
        base = base.where(SparePartTransaction.transaction_type == transaction_type)

    if spare_part_id:
        base = base.where(SparePartTransaction.spare_part_id == spare_part_id)

    if date_from:
        base = base.where(SparePartTransaction.created_at >= date_from)

    if date_to:
        base = base.where(SparePartTransaction.created_at <= date_to)

    if keyword:
        pattern = f"%{keyword}%"
        base = base.where(
            SparePart.name.ilike(pattern) | SparePart.code.ilike(pattern)
        )

    # 数据范围过滤（按备件归属部门，与列表口径一致）
    base = apply_equipment_scope(base, ctx, SparePart.department_id, "department_id")

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


async def get_spare_part_with_stock_by_id(
    db: AsyncSession,
    spare_part_id: uuid.UUID,
) -> SparePart | None:
    """按 ID 获取备件并填充库存/关联设备数等派生字段（详情与列表口径一致）"""
    spare_part = await get_spare_part_by_id(db, spare_part_id)
    if not spare_part:
        return None

    stock = await get_stock_by_spare_part_id(db, spare_part_id)
    spare_part.current_qty = stock.current_qty if stock else 0  # type: ignore[attr-defined]
    spare_part.min_qty = stock.safety_qty if stock else 0  # type: ignore[attr-defined]
    spare_part.safety_qty = stock.safety_qty if stock else 0  # type: ignore[attr-defined]
    spare_part.min_order_qty = stock.min_order_qty if stock else 1  # type: ignore[attr-defined]
    spare_part.warehouse_location = stock.warehouse_location if stock else None  # type: ignore[attr-defined]
    spare_part.is_low_stock = bool(  # type: ignore[attr-defined]
        stock and stock.safety_qty > 0 and stock.current_qty < stock.safety_qty
    )

    count_result = await db.execute(
        select(func.count())
        .select_from(EquipmentSparePart)
        .where(
            EquipmentSparePart.spare_part_id == spare_part_id,
            EquipmentSparePart.is_deleted == False,  # noqa: E712
        )
    )
    spare_part.equipment_count = count_result.scalar() or 0  # type: ignore[attr-defined]
    return spare_part


async def get_department_names_by_ids(
    db: AsyncSession,
    department_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """批量获取部门名称（一次查询）"""
    from app.platform.identity.models import Department

    if not department_ids:
        return {}
    result = await db.execute(
        select(Department.id, Department.name).where(
            Department.id.in_(department_ids),
            Department.is_deleted == False,  # noqa: E712
        )
    )
    return {row.id: row.name for row in result}


async def get_reserved_quantities(
    db: AsyncSession,
    spare_part_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """统计备件被「待验收」工单登记消耗的占用量。

    完工登记的 consumed_parts_data 在验收合格前不扣库存，但库存已被
    逻辑占用；台账展示可用量时需扣除，避免管理员误判可分配库存。
    """
    from app.modules.equipment.models.work_order import WorkOrder

    if not spare_part_ids:
        return {}
    id_set = set(spare_part_ids)
    result = await db.execute(
        select(WorkOrder.consumed_parts_data).where(
            WorkOrder.status == "待验收",
            WorkOrder.is_deleted == False,  # noqa: E712
            WorkOrder.consumed_parts_data.isnot(None),
        )
    )
    reserved: dict[uuid.UUID, int] = {}
    for (raw,) in result:
        try:
            parts = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parts, list):
            continue
        for p in parts:
            try:
                sp_id = uuid.UUID(str(p["spare_part_id"]))
                qty = int(p["quantity"])
            except (KeyError, ValueError, TypeError):
                continue
            if sp_id in id_set and qty > 0:
                reserved[sp_id] = reserved.get(sp_id, 0) + qty
    return reserved
