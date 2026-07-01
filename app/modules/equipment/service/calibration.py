"""Calibration service: business logic for plans and records."""

import uuid
from datetime import date as date_type
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import CalibrationPlan, CalibrationRecord
from app.modules.equipment.schemas import (
    CalibrationPlanCreate,
    CalibrationPlanUpdate,
    CalibrationRecordCreate,
)
from app.modules.equipment.service.data_scope import (
    verify_write_ownership,
)


def _add_months(d: date_type, months: int) -> date_type:
    """日期加N个月"""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(
        d.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][month - 1],
    )
    return date_type(year, month, day)


async def create_calibration_plan(
    db: AsyncSession,
    data: CalibrationPlanCreate,
    ctx: EquipmentAccessContext,
) -> CalibrationPlan:
    """创建校准计划"""
    plan_data = data.model_dump()

    # 自动计算下次校准日期
    if data.last_calibration_date:
        plan_data["next_calibration_date"] = _add_months(
            data.last_calibration_date, data.cycle_months
        )

    return await repo.create_calibration_plan(db, plan_data)


async def get_calibration_plan_by_id(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> CalibrationPlan:
    """获取校准计划"""
    plan = await repo.get_calibration_plan_by_id(db, plan_id)
    if not plan:
        raise NotFoundException("校准计划", str(plan_id))
    return plan


async def get_calibration_plans(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    equipment_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CalibrationPlan], int]:
    """获取校准计划列表"""
    return await repo.get_calibration_plans(
        db,
        ctx=ctx,
        equipment_id=equipment_id,
        status=status,
        page=page,
        page_size=page_size,
    )


async def update_calibration_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    data: CalibrationPlanUpdate,
    ctx: EquipmentAccessContext,
) -> CalibrationPlan:
    """更新校准计划"""
    plan = await get_calibration_plan_by_id(db, plan_id)
    await verify_write_ownership(ctx, plan, "created_by", "user_id")

    update_data = data.model_dump(exclude_unset=True)

    # 如果更新了周期或上次日期，重新计算下次日期
    cycle = update_data.get("cycle_months", plan.cycle_months)
    last_date = update_data.get("last_calibration_date", plan.last_calibration_date)

    # last_calibration_date 被显式清空时，同步清除 next_calibration_date
    if "last_calibration_date" in update_data and last_date is None:
        update_data["next_calibration_date"] = None
    elif cycle and last_date:
        update_data["next_calibration_date"] = _add_months(last_date, cycle)

    result = await repo.update_calibration_plan(db, plan_id, update_data)
    if not result:
        raise NotFoundException("校准计划", str(plan_id))
    return result


async def delete_calibration_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    ctx: EquipmentAccessContext,
) -> bool:
    """删除校准计划"""
    plan = await get_calibration_plan_by_id(db, plan_id)
    await verify_write_ownership(ctx, plan, "created_by", "user_id")
    return await repo.delete_calibration_plan(db, plan_id)


async def get_overdue_calibration_plans(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    days: int = 30,
) -> list[CalibrationPlan]:
    """查询到期/逾期的校准计划"""
    threshold = date_type.today() + timedelta(days=days)
    return await repo.get_calibration_plans_due(db, ctx, threshold)


async def create_calibration_record(
    db: AsyncSession,
    data: CalibrationRecordCreate,
    ctx: EquipmentAccessContext,
) -> CalibrationRecord:
    """创建校准记录"""
    plan = await get_calibration_plan_by_id(db, data.calibration_plan_id)

    # 计算下次校准日期
    next_due = _add_months(data.calibration_date, plan.cycle_months)

    record_data = data.model_dump()
    record_data["equipment_id"] = plan.equipment_id
    record_data["next_due_date"] = next_due

    record = await repo.create_calibration_record(db, record_data)

    # 更新计划的日期
    plan.last_calibration_date = data.calibration_date
    plan.next_calibration_date = next_due
    await db.flush()

    return record


async def get_calibration_record_by_id(
    db: AsyncSession,
    record_id: uuid.UUID,
) -> CalibrationRecord:
    """获取校准记录"""
    record = await repo.get_calibration_record_by_id(db, record_id)
    if not record:
        raise NotFoundException("校准记录", str(record_id))
    return record


async def get_calibration_records(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    equipment_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CalibrationRecord], int]:
    """获取校准记录列表"""
    return await repo.get_calibration_records(
        db,
        ctx=ctx,
        equipment_id=equipment_id,
        plan_id=plan_id,
        page=page,
        page_size=page_size,
    )
