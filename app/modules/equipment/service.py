"""Equipment service layer: business logic, validation, transaction orchestration."""

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import Equipment, EquipmentCategory, Location
from app.modules.equipment.schemas import (
    EquipmentCategoryCreate,
    EquipmentCategoryUpdate,
    EquipmentCreate,
    EquipmentUpdate,
    LocationCreate,
    LocationUpdate,
)


# ==================== 设备分类 ====================
async def create_equipment_category(
    db: AsyncSession,
    data: EquipmentCategoryCreate,
) -> EquipmentCategory:
    """创建设备分类"""
    # 检查编码是否重复
    if await repo.exists_category_by_code(db, data.code):
        raise DuplicateException("分类代码", data.code)

    return await repo.create_equipment_category(db, data.model_dump())


async def get_equipment_category_by_id(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> EquipmentCategory:
    """获取设备分类"""
    category = await repo.get_equipment_category_by_id(db, category_id)
    if not category:
        raise NotFoundException("设备分类", str(category_id))
    return category


async def get_equipment_categories(
    db: AsyncSession,
    parent_id: uuid.UUID | None = None,
) -> list[EquipmentCategory]:
    """获取设备分类列表"""
    return await repo.get_equipment_categories(db, parent_id)


async def get_equipment_category_tree(db: AsyncSession) -> list[EquipmentCategory]:
    """获取设备分类树形结构"""
    return await repo.get_equipment_category_tree(db)


async def update_equipment_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    data: EquipmentCategoryUpdate,
) -> EquipmentCategory:
    """更新设备分类"""
    if data.code is not None and await repo.exists_category_by_code(
        db, data.code, exclude_id=category_id
    ):
        raise DuplicateException("分类代码", data.code)

    category = await repo.update_equipment_category(
        db, category_id, data.model_dump(exclude_unset=True)
    )
    if not category:
        raise NotFoundException("设备分类", str(category_id))
    return category


async def delete_equipment_category(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> bool:
    """删除设备分类"""
    await get_equipment_category_by_id(db, category_id)

    children = await repo.get_equipment_categories(db, parent_id=category_id)
    if children:
        raise DuplicateException("子分类", "该分类下存在子分类，无法删除")

    equipment_count = await repo.count_equipments_by_category(db, category_id)
    if equipment_count > 0:
        raise DuplicateException("设备分类", "该分类下存在设备，无法删除")

    return await repo.delete_equipment_category(db, category_id)


# ==================== 位置管理 ====================
async def create_location(
    db: AsyncSession,
    data: LocationCreate,
) -> Location:
    """创建位置"""
    # 检查编码是否重复
    if await repo.exists_location_by_code(db, data.code):
        raise DuplicateException("位置代码", data.code)

    return await repo.create_location(db, data.model_dump())


async def get_location_by_id(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> Location:
    """获取位置"""
    location = await repo.get_location_by_id(db, location_id)
    if not location:
        raise NotFoundException("位置", str(location_id))
    return location


async def get_locations(
    db: AsyncSession,
    parent_id: uuid.UUID | None = None,
) -> list[Location]:
    """获取位置列表"""
    return await repo.get_locations(db, parent_id)


async def get_location_tree(db: AsyncSession) -> list[Location]:
    """获取位置树形结构"""
    return await repo.get_location_tree(db)


async def update_location(
    db: AsyncSession,
    location_id: uuid.UUID,
    data: LocationUpdate,
) -> Location:
    """更新位置"""
    if data.code is not None and await repo.exists_location_by_code(
        db, data.code, exclude_id=location_id
    ):
        raise DuplicateException("位置代码", data.code)

    location = await repo.update_location(
        db, location_id, data.model_dump(exclude_unset=True)
    )
    if not location:
        raise NotFoundException("位置", str(location_id))
    return location


async def delete_location(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> bool:
    """删除位置"""
    await get_location_by_id(db, location_id)

    children = await repo.get_locations(db, parent_id=location_id)
    if children:
        raise DuplicateException("子位置", "该位置下存在子位置，无法删除")

    equipment_count = await repo.count_equipments_by_location(db, location_id)
    if equipment_count > 0:
        raise DuplicateException("设备位置", "该位置下存在设备，无法删除")

    return await repo.delete_location(db, location_id)


# ==================== 设备管理 ====================
async def generate_equipment_no(
    db: AsyncSession,
    category_code: str,
) -> str:
    """生成设备编号"""
    max_no = await repo.get_max_equipment_no_by_category(db, category_code)
    if max_no:
        # 提取序号部分
        seq_str = max_no.split("-")[-1]
        seq = int(seq_str) + 1
    else:
        seq = 1
    return f"EQ-{category_code}-{seq:04d}"


async def create_equipment(
    db: AsyncSession,
    data: EquipmentCreate,
) -> Equipment:
    """创建设备"""
    category = await get_equipment_category_by_id(db, data.category_id)
    await get_location_by_id(db, data.location_id)

    equipment_no = await generate_equipment_no(db, category.code)

    equipment_data = data.model_dump()
    equipment_data["equipment_no"] = equipment_no

    try:
        return await repo.create_equipment(db, equipment_data)
    except IntegrityError:
        raise DuplicateException("设备编号", equipment_no)


async def get_equipment_by_id(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> Equipment:
    """获取设备"""
    equipment = await repo.get_equipment_by_id(db, equipment_id)
    if not equipment:
        raise NotFoundException("设备", str(equipment_id))
    return equipment


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
    return await repo.get_equipments(
        db, category_id, location_id, status, keyword, page, page_size
    )


async def update_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    data: EquipmentUpdate,
) -> Equipment:
    """更新设备"""
    equipment = await get_equipment_by_id(db, equipment_id)

    if data.category_id is not None:
        await get_equipment_category_by_id(db, data.category_id)
    if data.location_id is not None:
        await get_location_by_id(db, data.location_id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(equipment, key, value)
    await db.flush()
    await db.refresh(equipment)
    return equipment


async def delete_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> bool:
    """删除设备"""
    equipment = await get_equipment_by_id(db, equipment_id)
    equipment.is_deleted = True
    await db.flush()
    return True


async def get_equipment_statistics(db: AsyncSession) -> dict[str, Any]:
    """获取设备统计"""
    return await repo.get_equipment_statistics(db)
