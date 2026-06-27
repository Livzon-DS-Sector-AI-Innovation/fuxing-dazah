"""Calibration repository functions."""

import uuid
from datetime import date as date_type
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import CalibrationPlan, CalibrationRecord
from app.modules.equipment.service.data_scope import apply_equipment_scope


async def create_calibration_plan(
    db: AsyncSession,
    data: dict[str, Any],
) -> CalibrationPlan:
    """创建校准计划"""
    plan = CalibrationPlan(**data)
    db.add(plan)
    await db.flush()
    return plan


async def get_calibration_plan_by_id(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> CalibrationPlan | None:
    """根据ID获取校准计划"""
    result = await db.execute(
        select(CalibrationPlan).where(
            CalibrationPlan.id == plan_id,
            CalibrationPlan.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_calibration_plans(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    equipment_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CalibrationPlan], int]:
    """获取校准计划列表"""
    query = select(CalibrationPlan).where(
        CalibrationPlan.is_deleted == False  # noqa: E712
    )
    query = apply_equipment_scope(query, ctx, CalibrationPlan.created_by, "user_id")

    if equipment_id:
        query = query.where(CalibrationPlan.equipment_id == equipment_id)
    if status:
        query = query.where(CalibrationPlan.status == status)

    count_query = select(func.count()).select_from(
        query.with_only_columns(CalibrationPlan.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(CalibrationPlan.next_calibration_date)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_calibration_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    data: dict[str, Any],
) -> CalibrationPlan | None:
    """更新校准计划"""
    plan = await get_calibration_plan_by_id(db, plan_id)
    if not plan:
        return None
    for key, value in data.items():
        setattr(plan, key, value)
    await db.flush()
    await db.refresh(plan)
    return plan


async def delete_calibration_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> bool:
    """删除校准计划（软删除）"""
    plan = await get_calibration_plan_by_id(db, plan_id)
    if not plan:
        return False
    plan.is_deleted = True
    await db.flush()
    return True


async def get_calibration_plans_due(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    threshold: date_type,
) -> list[CalibrationPlan]:
    """查询到期/逾期的校准计划"""
    query = (
        select(CalibrationPlan)
        .where(
            CalibrationPlan.is_deleted == False,  # noqa: E712
            CalibrationPlan.status == "启用",
            CalibrationPlan.next_calibration_date <= threshold,
        )
    )
    query = apply_equipment_scope(query, ctx, CalibrationPlan.created_by, "user_id")
    query = query.order_by(CalibrationPlan.next_calibration_date)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_calibration_record(
    db: AsyncSession,
    data: dict[str, Any],
) -> CalibrationRecord:
    """创建校准记录"""
    record = CalibrationRecord(**data)
    db.add(record)
    await db.flush()
    return record


async def get_calibration_record_by_id(
    db: AsyncSession,
    record_id: uuid.UUID,
) -> CalibrationRecord | None:
    """根据ID获取校准记录"""
    result = await db.execute(
        select(CalibrationRecord).where(
            CalibrationRecord.id == record_id,
            CalibrationRecord.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_calibration_records(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    equipment_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CalibrationRecord], int]:
    """获取校准记录列表"""
    query = select(CalibrationRecord).where(
        CalibrationRecord.is_deleted == False  # noqa: E712
    )
    query = apply_equipment_scope(query, ctx, CalibrationRecord.created_by, "user_id")

    if equipment_id:
        query = query.where(CalibrationRecord.equipment_id == equipment_id)
    if plan_id:
        query = query.where(CalibrationRecord.calibration_plan_id == plan_id)

    count_query = select(func.count()).select_from(
        query.with_only_columns(CalibrationRecord.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(CalibrationRecord.calibration_date.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total
