"""Equipment database queries live here."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models import Equipment, EquipmentCategory, Location


def _escape_like(value: str) -> str:
    """Escape special characters in LIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ==================== 设备分类 ====================
async def exists_category_by_code(
    db: AsyncSession,
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Check if category code exists."""
    query = select(EquipmentCategory.id).where(
        EquipmentCategory.code == code,
        EquipmentCategory.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(EquipmentCategory.id != exclude_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def exists_location_by_code(
    db: AsyncSession,
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Check if location code exists."""
    query = select(Location.id).where(
        Location.code == code,
        Location.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(Location.id != exclude_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def create_equipment_category(
    db: AsyncSession,
    data: dict[str, Any],
) -> EquipmentCategory:
    """创建设备分类"""
    category = EquipmentCategory(**data)
    db.add(category)
    await db.flush()
    return category


async def get_equipment_category_by_id(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> EquipmentCategory | None:
    """根据ID获取设备分类"""
    result = await db.execute(
        select(EquipmentCategory).where(
            EquipmentCategory.id == category_id,
            EquipmentCategory.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_equipment_categories(
    db: AsyncSession,
    parent_id: uuid.UUID | None = None,
) -> list[EquipmentCategory]:
    """获取设备分类列表"""
    query = select(EquipmentCategory).where(
        EquipmentCategory.is_deleted == False  # noqa: E712
    )
    if parent_id is not None:
        query = query.where(EquipmentCategory.parent_id == parent_id)
    else:
        query = query.where(EquipmentCategory.parent_id.is_(None))
    query = query.order_by(EquipmentCategory.code)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_equipment_category_tree(db: AsyncSession) -> list[EquipmentCategory]:
    """获取设备分类树形结构"""
    result = await db.execute(
        select(EquipmentCategory)
        .where(EquipmentCategory.is_deleted == False)  # noqa: E712
        .options(selectinload(EquipmentCategory.children))
        .order_by(EquipmentCategory.code)
    )
    categories = list(result.scalars().all())

    category_map: dict[uuid.UUID, EquipmentCategory] = {
        cat.id: cat for cat in categories
    }
    for category in categories:
        category.children = []
    root_categories: list[EquipmentCategory] = []

    for category in categories:
        if category.parent_id is None:
            root_categories.append(category)
        else:
            parent = category_map.get(category.parent_id)
            if parent:
                parent.children.append(category)

    return root_categories


async def update_equipment_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    data: dict[str, Any],
) -> EquipmentCategory | None:
    """更新设备分类"""
    category = await get_equipment_category_by_id(db, category_id)
    if not category:
        return None
    for key, value in data.items():
        setattr(category, key, value)
    await db.flush()
    await db.refresh(category)
    return category


async def delete_equipment_category(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> bool:
    """删除设备分类（软删除）"""
    category = await get_equipment_category_by_id(db, category_id)
    if not category:
        return False
    category.is_deleted = True
    await db.flush()
    return True


# ==================== 位置管理 ====================
async def create_location(
    db: AsyncSession,
    data: dict[str, Any],
) -> Location:
    """创建位置"""
    location = Location(**data)
    db.add(location)
    await db.flush()
    return location


async def get_location_by_id(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> Location | None:
    """根据ID获取位置"""
    result = await db.execute(
        select(Location).where(
            Location.id == location_id,
            Location.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_locations(
    db: AsyncSession,
    parent_id: uuid.UUID | None = None,
) -> list[Location]:
    """获取位置列表"""
    query = select(Location).where(Location.is_deleted == False)  # noqa: E712
    if parent_id is not None:
        query = query.where(Location.parent_id == parent_id)
    else:
        query = query.where(Location.parent_id.is_(None))
    query = query.order_by(Location.code)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_location_tree(db: AsyncSession) -> list[Location]:
    """获取位置树形结构"""
    result = await db.execute(
        select(Location)
        .where(Location.is_deleted == False)  # noqa: E712
        .options(selectinload(Location.children))
        .order_by(Location.code)
    )
    locations = list(result.scalars().all())

    location_map: dict[uuid.UUID, Location] = {loc.id: loc for loc in locations}
    for location in locations:
        location.children = []
    root_locations: list[Location] = []

    for location in locations:
        if location.parent_id is None:
            root_locations.append(location)
        else:
            parent = location_map.get(location.parent_id)
            if parent:
                parent.children.append(location)

    return root_locations


async def update_location(
    db: AsyncSession,
    location_id: uuid.UUID,
    data: dict[str, Any],
) -> Location | None:
    """更新位置"""
    location = await get_location_by_id(db, location_id)
    if not location:
        return None
    for key, value in data.items():
        setattr(location, key, value)
    await db.flush()
    await db.refresh(location)
    return location


async def delete_location(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> bool:
    """删除位置（软删除）"""
    location = await get_location_by_id(db, location_id)
    if not location:
        return False
    location.is_deleted = True
    await db.flush()
    return True


# ==================== 设备管理 ====================
async def create_equipment(
    db: AsyncSession,
    data: dict[str, Any],
) -> Equipment:
    """创建设备"""
    equipment = Equipment(**data)
    db.add(equipment)
    await db.flush()
    return equipment


async def get_equipment_by_id(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> Equipment | None:
    """根据ID获取设备"""
    result = await db.execute(
        select(Equipment).where(
            Equipment.id == equipment_id,
            Equipment.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_equipment_by_no(
    db: AsyncSession,
    equipment_no: str,
) -> Equipment | None:
    """根据设备编号获取设备"""
    result = await db.execute(
        select(Equipment).where(
            Equipment.equipment_no == equipment_no,
            Equipment.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_equipments(
    db: AsyncSession,
    category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Equipment], int]:
    """获取设备列表"""
    query = select(Equipment).where(Equipment.is_deleted == False)  # noqa: E712

    if category_id:
        query = query.where(Equipment.category_id == category_id)
    if location_id:
        query = query.where(Equipment.location_id == location_id)
    if status:
        query = query.where(Equipment.status == status)
    if keyword:
        escaped = _escape_like(keyword)
        query = query.where(
            Equipment.equipment_no.ilike(f"%{escaped}%", escape="\\")
            | Equipment.name.ilike(f"%{escaped}%", escape="\\")
        )

    # 获取总数
    count_query = select(func.count()).select_from(
        query.with_only_columns(Equipment.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(Equipment.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    equipments = list(result.scalars().all())

    return equipments, total


async def update_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    data: dict[str, Any],
) -> Equipment | None:
    """更新设备"""
    equipment = await get_equipment_by_id(db, equipment_id)
    if not equipment:
        return None
    for key, value in data.items():
        setattr(equipment, key, value)
    await db.flush()
    await db.refresh(equipment)
    return equipment


async def delete_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> bool:
    """删除设备（软删除）"""
    equipment = await get_equipment_by_id(db, equipment_id)
    if not equipment:
        return False
    equipment.is_deleted = True
    await db.flush()
    return True


async def count_equipments_by_category(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> int:
    """统计指定分类下的设备数量"""
    result = await db.execute(
        select(func.count())
        .select_from(Equipment)
        .where(
            Equipment.category_id == category_id,
            Equipment.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar() or 0


async def count_equipments_by_location(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> int:
    """统计指定位置下的设备数量"""
    result = await db.execute(
        select(func.count())
        .select_from(Equipment)
        .where(
            Equipment.location_id == location_id,
            Equipment.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar() or 0


async def get_max_equipment_no_by_category(
    db: AsyncSession,
    category_code: str,
) -> str | None:
    """获取指定分类的最大设备编号"""
    pattern = f"EQ-{category_code}-%"
    result = await db.execute(
        select(Equipment.equipment_no)
        .where(
            Equipment.equipment_no.like(pattern),
            Equipment.is_deleted == False,  # noqa: E712
        )
        .order_by(Equipment.equipment_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_equipment_statistics(db: AsyncSession) -> dict[str, Any]:
    """获取设备统计"""
    # 总数
    total_result = await db.execute(
        select(func.count()).where(Equipment.is_deleted == False)  # noqa: E712
    )
    total = total_result.scalar() or 0

    # 按状态统计
    status_result = await db.execute(
        select(Equipment.status, func.count())
        .where(Equipment.is_deleted == False)  # noqa: E712
        .group_by(Equipment.status)
    )
    by_status = {row[0]: row[1] for row in status_result.all()}

    # 按分类统计
    category_result = await db.execute(
        select(EquipmentCategory.name, func.count())
        .join(Equipment, Equipment.category_id == EquipmentCategory.id)
        .where(Equipment.is_deleted == False)  # noqa: E712
        .group_by(EquipmentCategory.name)
    )
    by_category = {row[0]: row[1] for row in category_result.all()}

    # 按位置统计
    location_result = await db.execute(
        select(Location.name, func.count())
        .join(Equipment, Equipment.location_id == Location.id)
        .where(Equipment.is_deleted == False)  # noqa: E712
        .group_by(Location.name)
    )
    by_location = {row[0]: row[1] for row in location_result.all()}

    return {
        "total": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_location": by_location,
    }
