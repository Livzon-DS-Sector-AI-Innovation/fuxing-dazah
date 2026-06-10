"""Equipment database queries live here."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    Location,
)
from app.platform.identity.models import Department, User


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


async def _get_category_child_ids(
    db: AsyncSession,
    parent_id: uuid.UUID,
) -> list[uuid.UUID]:
    """递归收集指定分类及其所有子孙分类的ID"""
    result = await db.execute(
        select(EquipmentCategory.id).where(
            EquipmentCategory.parent_id == parent_id,
            EquipmentCategory.is_deleted == False,  # noqa: E712
        )
    )
    child_ids = list(result.scalars().all())
    all_ids: list[uuid.UUID] = [parent_id]
    for child_id in child_ids:
        all_ids.extend(await _get_category_child_ids(db, child_id))
    return all_ids


async def _get_location_child_ids(
    db: AsyncSession,
    parent_id: uuid.UUID,
) -> list[uuid.UUID]:
    """递归收集指定位置及其所有子孙位置的ID"""
    result = await db.execute(
        select(Location.id).where(
            Location.parent_id == parent_id,
            Location.is_deleted == False,  # noqa: E712
        )
    )
    child_ids = list(result.scalars().all())
    all_ids: list[uuid.UUID] = [parent_id]
    for child_id in child_ids:
        all_ids.extend(await _get_location_child_ids(db, child_id))
    return all_ids


# ==================== 设备管理 ====================
async def create_equipment(
    db: AsyncSession,
    data: dict[str, Any],
    category_ids: list[uuid.UUID] | None = None,
) -> Equipment:
    """创建设备"""
    # 提取 category_ids，不传给 Equipment 构造
    cids = category_ids or data.pop("category_ids", [])
    equipment = Equipment(**data)
    db.add(equipment)
    await db.flush()

    # 创建分类关联（去重）
    seen: set[uuid.UUID] = set()
    for cid in cids:
        if cid not in seen:
            seen.add(cid)
            db.add(EquipmentCategoryLink(equipment_id=equipment.id, category_id=cid))
    await db.flush()

    # eager re-fetch
    return await _refetch_equipment(db, equipment.id)


async def _refetch_equipment(
    db: AsyncSession, equipment_id: uuid.UUID
) -> Equipment | None:
    """eager re-fetch 设备及关联"""
    result = await db.execute(
        select(Equipment)
        .options(selectinload(Equipment.category_links).selectinload(EquipmentCategoryLink.category))
        .where(Equipment.id == equipment_id, Equipment.is_deleted == False)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def get_equipment_by_id(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> Equipment | None:
    """根据ID获取设备"""
    result = await db.execute(
        select(Equipment)
        .options(selectinload(Equipment.category_links).selectinload(EquipmentCategoryLink.category))
        .where(
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
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Equipment], int]:
    """获取设备列表"""
    query = (
        select(Equipment)
        .options(selectinload(Equipment.category_links).selectinload(EquipmentCategoryLink.category))
        .where(Equipment.is_deleted == False)  # noqa: E712
    )

    if category_id:
        category_ids = await _get_category_child_ids(db, category_id)
        query = query.join(
            EquipmentCategoryLink,
            EquipmentCategoryLink.equipment_id == Equipment.id,
        ).where(
            EquipmentCategoryLink.category_id.in_(category_ids),
            EquipmentCategoryLink.is_deleted == False,  # noqa: E712
        ).distinct()
    if location_id:
        location_ids = await _get_location_child_ids(db, location_id)
        query = query.where(Equipment.location_id.in_(location_ids))
    if department_id:
        query = query.where(Equipment.department_id == department_id)
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
    category_ids: list[uuid.UUID] | None = None,
) -> Equipment | None:
    """更新设备"""
    equipment = await get_equipment_by_id(db, equipment_id)
    if not equipment:
        return None

    # 提取 category_ids
    cids = category_ids if category_ids is not None else data.pop("category_ids", None)

    for key, value in data.items():
        setattr(equipment, key, value)
    await db.flush()

    # 更新分类关联
    if cids is not None:
        # 去重
        cids = list(dict.fromkeys(cids))

        # 查询该设备所有已有的关联（包括软删除的）
        all_existing_result = await db.execute(
            select(EquipmentCategoryLink).where(
                EquipmentCategoryLink.equipment_id == equipment_id,
            )
        )
        existing_links = list(all_existing_result.scalars().all())
        existing_by_cid: dict[uuid.UUID, EquipmentCategoryLink] = {
            link.category_id: link for link in existing_links
        }

        new_cid_set = set(cids)

        for link in existing_links:
            if link.category_id in new_cid_set:
                # 在新列表中：恢复（如果被软删除）或保持不变
                if link.is_deleted:
                    link.is_deleted = False
            else:
                # 不在新列表中：软删除
                if not link.is_deleted:
                    link.is_deleted = True

        # 创建新的关联（之前不存在的分类）
        for cid in cids:
            if cid not in existing_by_cid:
                db.add(EquipmentCategoryLink(equipment_id=equipment_id, category_id=cid))

        await db.flush()

    return await _refetch_equipment(db, equipment_id)


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
    """统计指定分类下的设备数量（通过联结表）"""
    result = await db.execute(
        select(func.count(func.distinct(EquipmentCategoryLink.equipment_id)))
        .select_from(EquipmentCategoryLink)
        .join(Equipment, Equipment.id == EquipmentCategoryLink.equipment_id)
        .where(
            EquipmentCategoryLink.category_id == category_id,
            EquipmentCategoryLink.is_deleted == False,  # noqa: E712
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

    # 按分类统计（通过联结表）
    category_result = await db.execute(
        select(EquipmentCategory.name, func.count(func.distinct(EquipmentCategoryLink.equipment_id)))
        .select_from(EquipmentCategoryLink)
        .join(Equipment, Equipment.id == EquipmentCategoryLink.equipment_id)
        .join(EquipmentCategory, EquipmentCategory.id == EquipmentCategoryLink.category_id)
        .where(
            Equipment.is_deleted == False,  # noqa: E712
            EquipmentCategoryLink.is_deleted == False,  # noqa: E712
        )
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


async def get_departments_for_select(db: AsyncSession) -> list[dict[str, Any]]:
    """获取可选部门列表（含负责人姓名），供下拉使用"""
    query = (
        select(
            Department.id.label("id"),
            Department.name.label("name"),
            Department.leader_user_id.label("leader_user_id"),
            User.name.label("leader_name"),
        )
        .outerjoin(User, Department.leader_user_id == User.feishu_open_id)
        .where(
            Department.status_is_deleted.isnot(True),
            Department.is_deleted == False,  # noqa: E712
        )
        .order_by(Department.name)
    )
    result = await db.execute(query)
    rows = result.all()
    return [dict(row._mapping) for row in rows]


async def get_department_info(
    db: AsyncSession, department_id: uuid.UUID
) -> dict[str, Any] | None:
    """获取单个部门信息（含负责人姓名）"""
    query = (
        select(
            Department.id.label("id"),
            Department.name.label("name"),
            Department.leader_user_id.label("leader_user_id"),
            User.name.label("leader_name"),
        )
        .outerjoin(User, Department.leader_user_id == User.feishu_open_id)
        .where(
            Department.id == department_id,
            Department.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(query)
    row = result.one_or_none()
    if row is None:
        return None
    return dict(row._mapping)
