"""Maintenance plan service: business logic for plans."""

import uuid
from datetime import date as date_type
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import MaintenancePlan
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanUpdate,
)


def _calculate_next_maintenance_date(
    last_date: date_type,
    frequency: int,
    frequency_unit: str,
) -> date_type:
    """计算下次维护日期"""
    if frequency_unit == "天":
        return last_date + timedelta(days=frequency)
    elif frequency_unit == "周":
        return last_date + timedelta(weeks=frequency)
    elif frequency_unit == "月":
        return _add_months(last_date, frequency)
    elif frequency_unit == "年":
        return _add_months(last_date, frequency * 12)
    return last_date


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


async def create_maintenance_plan(
    db: AsyncSession,
    data: MaintenancePlanCreate,
) -> MaintenancePlan:
    """创建维护计划"""
    plan_data = data.model_dump()

    # 自动计算下次维护日期
    if data.last_maintenance_date:
        plan_data["next_maintenance_date"] = _calculate_next_maintenance_date(
            data.last_maintenance_date,
            data.frequency,
            data.frequency_unit,
        )

    return await repo.create_maintenance_plan(db, plan_data)


async def get_maintenance_plan_by_id(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> MaintenancePlan:
    """获取维护计划"""
    plan = await repo.get_maintenance_plan_by_id(db, plan_id)
    if not plan:
        raise NotFoundException("维护计划", str(plan_id))
    return plan


async def get_maintenance_plans(
    db: AsyncSession,
    equipment_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MaintenancePlan], int]:
    """获取维护计划列表"""
    return await repo.get_maintenance_plans(
        db,
        equipment_id=equipment_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


async def update_maintenance_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    data: MaintenancePlanUpdate,
) -> MaintenancePlan:
    """更新维护计划"""
    plan = await get_maintenance_plan_by_id(db, plan_id)

    update_data = data.model_dump(exclude_unset=True)

    # 如果更新了频率或上次日期，重新计算下次日期
    frequency = update_data.get("frequency", plan.frequency)
    frequency_unit = update_data.get("frequency_unit", plan.frequency_unit)
    last_date = update_data.get(
        "last_maintenance_date", plan.last_maintenance_date
    )

    # last_maintenance_date 被显式清空时，同步清除 next_maintenance_date
    if "last_maintenance_date" in update_data and last_date is None:
        update_data["next_maintenance_date"] = None
    elif frequency and frequency_unit and last_date:
        update_data["next_maintenance_date"] = _calculate_next_maintenance_date(
            last_date, frequency, frequency_unit
        )

    result = await repo.update_maintenance_plan(db, plan_id, update_data)
    if not result:
        raise NotFoundException("维护计划", str(plan_id))
    return result


async def delete_maintenance_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> bool:
    """删除维护计划"""
    await get_maintenance_plan_by_id(db, plan_id)
    return await repo.delete_maintenance_plan(db, plan_id)


async def get_overdue_maintenance_plans(
    db: AsyncSession,
    days: int = 30,
) -> list[MaintenancePlan]:
    """查询到期/逾期的维护计划"""
    threshold = date_type.today() + timedelta(days=days)
    return await repo.get_maintenance_plans_due(db, threshold)
