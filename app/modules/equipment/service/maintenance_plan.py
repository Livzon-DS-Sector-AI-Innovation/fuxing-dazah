"""Maintenance plan service: business logic for plans."""

import logging
import uuid
from datetime import date as date_type
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import MaintenancePlan
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanUpdate,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


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


async def generate_due_work_orders(
    db: AsyncSession,
) -> tuple[int, int]:
    """扫描到期维护计划，自动创建"计划维护"工单。

    Returns:
        (created_count, skipped_count) 元组
    """
    today = date_type.today()

    # 查询所有到期的启用计划
    due_plans = await repo.get_maintenance_plans_due(db, today)

    created_count = 0
    skipped_count = 0

    for plan in due_plans:
        # 防重：last_generated_date >= next_maintenance_date 则跳过
        if (
            plan.last_generated_date is not None
            and plan.next_maintenance_date is not None
            and plan.last_generated_date >= plan.next_maintenance_date
        ):
            skipped_count += 1
            continue

        # 校验设备存在且状态有效
        equipment = await repo.get_equipment_by_id(db, plan.equipment_id)
        if not equipment:
            logger.warning(
                "维护计划 %s (%s) 的设备不存在或已删除，跳过",
                plan.id,
                plan.plan_name,
            )
            skipped_count += 1
            continue

        if equipment.status in ("停用", "报废"):
            logger.info(
                "维护计划 %s (%s) 的设备状态为 %s，跳过",
                plan.id,
                plan.plan_name,
                equipment.status,
            )
            skipped_count += 1
            continue

        # 检查该计划是否已有未关闭工单（双重保险）
        has_unclosed = await repo.exists_unclosed_work_order_for_plan(
            db, plan.id
        )
        if has_unclosed:
            logger.info(
                "维护计划 %s (%s) 已有未关闭工单，跳过",
                plan.id,
                plan.plan_name,
            )
            skipped_count += 1
            continue

        # 生成工单（带重试，处理工单号并发冲突）
        work_order_created = False
        for attempt in range(_MAX_RETRIES):
            wo_no = await _generate_work_order_no(db)
            wo_data: dict[str, object] = {
                "work_order_no": wo_no,
                "equipment_id": plan.equipment_id,
                "order_type": "计划维护",
                "priority": "中",
                "status": "待处理",
                "reporter_id": None,  # 系统自动生成，无报修人
                "maintenance_plan_id": plan.id,
                "responsible_person_id": plan.responsible_person_id,
                "planned_start_date": plan.next_maintenance_date,
                "original_equipment_status": equipment.status,
            }
            try:
                await repo.create_work_order(db, wo_data)
                # 更新计划的 last_generated_date 防重
                plan.last_generated_date = plan.next_maintenance_date
                await db.flush()

                created_count += 1
                work_order_created = True
                logger.info(
                    "自动生成工单 %s (计划=%s, 设备=%s)",
                    wo_no,
                    plan.plan_name,
                    equipment.name,
                )
                break
            except IntegrityError:
                if attempt < _MAX_RETRIES - 1:
                    await db.rollback()
                    continue
                logger.error(
                    "维护计划 %s 工单号生成失败（重试 %d 次后放弃）",
                    plan.id,
                    _MAX_RETRIES,
                )

        if not work_order_created:
            skipped_count += 1

    return created_count, skipped_count


async def _generate_work_order_no(db: AsyncSession) -> str:
    """生成工单号：WO-{yyyyMMdd}-{seq:04d}（scheduler 内部使用）"""
    max_no = await repo.get_max_work_order_no(db)
    today = datetime.now().strftime("%Y%m%d")
    if max_no:
        seq_str = max_no.split("-")[-1]
        seq = int(seq_str) + 1
    else:
        seq = 1
    return f"WO-{today}-{seq:04d}"
