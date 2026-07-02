"""Inspection template repository functions."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import InspectionTemplate, InspectionTemplateItem
from app.modules.equipment.service.data_scope import apply_equipment_scope


async def create_inspection_template(
    db: AsyncSession,
    data: dict[str, Any],
    items: list[dict[str, Any]] | None = None,
) -> InspectionTemplate:
    """创建巡检模板"""
    template = InspectionTemplate(**data)
    db.add(template)
    await db.flush()

    if items:
        for item_data in items:
            item = InspectionTemplateItem(
                template_id=template.id, **item_data
            )
            db.add(item)
        await db.flush()

    # 用 eager re-fetch 加载 items，避免 relationship.__set__ 读取旧值或
    # Pydantic model_validate 访问关系时触发惰性加载 → MissingGreenlet
    result = await db.execute(
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(InspectionTemplate.id == template.id)
    )
    return result.scalar_one()


async def get_inspection_template_by_id(
    db: AsyncSession,
    template_id: uuid.UUID,
    ctx: EquipmentAccessContext | None = None,
) -> InspectionTemplate | None:
    """根据ID获取巡检模板（含检查项）"""
    query = (
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(
            InspectionTemplate.id == template_id,
            InspectionTemplate.is_deleted == False,  # noqa: E712
        )
    )
    if ctx:
        query = apply_equipment_scope(
            query, ctx, InspectionTemplate.created_by, mode="user_id"
        )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_inspection_template_by_name(
    db: AsyncSession,
    name: str,
    ctx: EquipmentAccessContext | None = None,
) -> InspectionTemplate | None:
    """根据模板名称精确查找巡检模板（含检查项）"""
    query = (
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(
            InspectionTemplate.name == name,
            InspectionTemplate.is_deleted == False,  # noqa: E712
        )
    )
    if ctx:
        query = apply_equipment_scope(
            query, ctx, InspectionTemplate.created_by, mode="user_id"
        )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_inspection_templates(
    db: AsyncSession,
    equipment_category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    ctx: EquipmentAccessContext | None = None,
) -> tuple[list[InspectionTemplate], int]:
    """获取巡检模板列表"""
    query = (
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(InspectionTemplate.is_deleted == False)  # noqa: E712
    )
    if equipment_category_id:
        query = query.where(
            InspectionTemplate.equipment_category_id == equipment_category_id
        )
    if is_active is not None:
        query = query.where(InspectionTemplate.is_active == is_active)
    if keyword:
        query = query.where(InspectionTemplate.name.ilike(f"%{keyword}%"))
    if ctx:
        query = apply_equipment_scope(
            query, ctx, InspectionTemplate.created_by, mode="user_id"
        )

    count_query = select(func.count()).select_from(
        query.with_only_columns(InspectionTemplate.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(InspectionTemplate.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_inspection_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    data: dict[str, Any],
) -> InspectionTemplate | None:
    """更新巡检模板"""
    template = await get_inspection_template_by_id(db, template_id)
    if not template:
        return None
    for key, value in data.items():
        setattr(template, key, value)
    await db.flush()
    # 用 eager re-fetch 替代 db.refresh，避免 expire 已加载的 items 关系
    result = await db.execute(
        select(InspectionTemplate)
        .options(selectinload(InspectionTemplate.items))
        .where(
            InspectionTemplate.id == template_id,
            InspectionTemplate.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one()


async def delete_inspection_template(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> bool:
    """删除巡检模板（软删除）"""
    template = await get_inspection_template_by_id(db, template_id)
    if not template:
        return False
    template.is_deleted = True
    await db.flush()
    return True


async def create_template_item(
    db: AsyncSession,
    data: dict[str, Any],
) -> InspectionTemplateItem:
    """创建检查项"""
    item = InspectionTemplateItem(**data)
    db.add(item)
    await db.flush()
    return item


async def get_template_item_by_id(
    db: AsyncSession,
    item_id: uuid.UUID,
) -> InspectionTemplateItem | None:
    """根据ID获取检查项"""
    result = await db.execute(
        select(InspectionTemplateItem).where(
            InspectionTemplateItem.id == item_id,
            InspectionTemplateItem.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_template_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    data: dict[str, Any],
) -> InspectionTemplateItem | None:
    """更新检查项"""
    item = await get_template_item_by_id(db, item_id)
    if not item:
        return None
    for key, value in data.items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return item


async def delete_template_item(
    db: AsyncSession,
    item_id: uuid.UUID,
) -> bool:
    """删除检查项（软删除）"""
    item = await get_template_item_by_id(db, item_id)
    if not item:
        return False
    item.is_deleted = True
    await db.flush()
    return True
