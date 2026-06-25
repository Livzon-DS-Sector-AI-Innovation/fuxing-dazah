"""Maintenance plan repository functions."""

import uuid
from datetime import date as date_type
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models import MaintenancePlan


async def create_maintenance_plan(
    db: AsyncSession,
    data: dict[str, Any],
) -> MaintenancePlan:
    """创建维护计划"""
    plan = MaintenancePlan(**data)
    db.add(plan)
    await db.flush()
    return plan


async def get_maintenance_plan_by_id(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> MaintenancePlan | None:
    """根据ID获取维护计划"""
    result = await db.execute(
        select(MaintenancePlan)
        .options(
            selectinload(MaintenancePlan.equipment),
            selectinload(MaintenancePlan.executor),
        )
        .where(
            MaintenancePlan.id == plan_id,
            MaintenancePlan.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_maintenance_plans(
    db: AsyncSession,
    equipment_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MaintenancePlan], int]:
    """获取维护计划列表"""
    query = (
        select(MaintenancePlan)
        .options(
            selectinload(MaintenancePlan.equipment),
            selectinload(MaintenancePlan.executor),
        )
        .where(MaintenancePlan.is_deleted == False)  # noqa: E712
    )
    if equipment_id:
        query = query.where(MaintenancePlan.equipment_id == equipment_id)
    if category_id:
        query = query.where(MaintenancePlan.category_id == category_id)
    if status:
        query = query.where(MaintenancePlan.status == status)
    if keyword:
        query = query.where(MaintenancePlan.plan_name.ilike(f"%{keyword}%"))

    count_query = select(func.count()).select_from(
        query.with_only_columns(MaintenancePlan.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MaintenancePlan.next_maintenance_date)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_maintenance_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    data: dict[str, Any],
) -> MaintenancePlan | None:
    """更新维护计划"""
    plan = await get_maintenance_plan_by_id(db, plan_id)
    if not plan:
        return None
    for key, value in data.items():
        setattr(plan, key, value)
    await db.flush()
    return await get_maintenance_plan_by_id(db, plan_id)


async def delete_maintenance_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> bool:
    """删除维护计划（软删除）"""
    plan = await get_maintenance_plan_by_id(db, plan_id)
    if not plan:
        return False
    plan.is_deleted = True
    await db.flush()
    return True


async def get_maintenance_plans_due(
    db: AsyncSession,
    threshold: date_type,
) -> list[MaintenancePlan]:
    """查询到期/逾期的维护计划"""
    result = await db.execute(
        select(MaintenancePlan)
        .options(
            selectinload(MaintenancePlan.equipment),
            selectinload(MaintenancePlan.executor),
        )
        .where(
            MaintenancePlan.is_deleted == False,  # noqa: E712
            MaintenancePlan.status == "启用",
            MaintenancePlan.next_maintenance_date <= threshold,
        )
        .order_by(MaintenancePlan.next_maintenance_date)
    )
    return list(result.scalars().all())


async def exists_unclosed_work_order_for_plan(
    db: AsyncSession,
    maintenance_plan_id: uuid.UUID,
) -> bool:
    """检查某维护计划是否已有未关闭的工单（防重复生成）"""
    from app.modules.equipment.models.work_order import WorkOrder

    result = await db.execute(
        select(func.count())
        .select_from(WorkOrder)
        .where(
            WorkOrder.maintenance_plan_id == maintenance_plan_id,
            WorkOrder.status.notin_(["已完成", "已关闭"]),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )
    return (result.scalar() or 0) > 0


async def get_equipment_ids_by_category(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> list[uuid.UUID]:
    """获取某分类下所有非停用/报废设备的ID列表"""
    from app.modules.equipment.models.equipment import (
        Equipment,
        EquipmentCategoryLink,
    )

    result = await db.execute(
        select(Equipment.id)
        .join(
            EquipmentCategoryLink,
            EquipmentCategoryLink.equipment_id == Equipment.id,
        )
        .where(
            EquipmentCategoryLink.category_id == category_id,
            EquipmentCategoryLink.is_deleted == False,  # noqa: E712
            Equipment.is_deleted == False,  # noqa: E712
            Equipment.status.notin_(["停用", "报废"]),
        )
    )
    return [row[0] for row in result.all()]
