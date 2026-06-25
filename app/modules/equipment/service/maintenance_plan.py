"""Maintenance plan service: business logic for plans."""

import logging
import uuid
from datetime import date as date_type
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import MaintenancePlan
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanUpdate,
)
from app.modules.equipment.service.work_order import (
    generate_work_order_no,
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
    # 校验 equipment_id 和 category_id 互斥（schema 已有，这里做二次保险）
    if (data.equipment_id is None and data.category_id is None) or \
       (data.equipment_id is not None and data.category_id is not None):
        raise AppException(
            message="equipment_id 和 category_id 必须恰好提供一个"
        )

    plan_data = data.model_dump()

    # 自动计算下次维护日期
    if data.last_maintenance_date:
        plan_data["next_maintenance_date"] = _calculate_next_maintenance_date(
            data.last_maintenance_date,
            data.frequency,
            data.frequency_unit,
        )

    plan = await repo.create_maintenance_plan(db, plan_data)
    # 创建后 re-fetch 加载关联数据
    return await repo.get_maintenance_plan_by_id(db, plan.id)


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
    category_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MaintenancePlan], int]:
    """获取维护计划列表"""
    return await repo.get_maintenance_plans(
        db,
        equipment_id=equipment_id,
        category_id=category_id,
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

        # 确定目标设备列表
        if plan.category_id:
            # category 模式：查询分类下所有可用设备
            equipment_ids = await repo.get_equipment_ids_by_category(
                db, plan.category_id
            )
            if not equipment_ids:
                logger.info(
                    "维护计划 %s (%s) 的分类下无可用设备，跳过",
                    plan.id, plan.plan_name,
                )
                skipped_count += 1
                continue
        elif plan.equipment_id:
            equipment_ids = [plan.equipment_id]
        else:
            skipped_count += 1
            continue

        # 检查该计划是否已有未关闭工单（提前到循环外，避免 N 次重复查询）
        has_unclosed = await repo.exists_unclosed_work_order_for_plan(
            db, plan.id
        )
        if has_unclosed:
            logger.info(
                "维护计划 %s (%s) 已有未关闭工单，跳过",
                plan.id, plan.plan_name,
            )
            skipped_count += 1
            continue

        # 批量查询所有目标设备（避免 N+1）
        from app.modules.equipment.models.equipment import Equipment

        eq_result = await db.execute(
            select(Equipment).where(
                Equipment.id.in_(equipment_ids),
                Equipment.is_deleted == False,  # noqa: E712
            )
        )
        eq_map = {e.id: e for e in eq_result.scalars().all()}

        any_created = False
        for eq_id in equipment_ids:
            equipment = eq_map.get(eq_id)
            if not equipment:
                logger.warning(
                    "维护计划 %s (%s) 的设备 %s 不存在或已删除，跳过",
                    plan.id, plan.plan_name, eq_id,
                )
                continue

            if equipment.status in ("停用", "报废"):
                logger.info(
                    "维护计划 %s (%s) 的设备 %s 状态为 %s，跳过",
                    plan.id, plan.plan_name, equipment.name, equipment.status,
                )
                continue

            # 生成工单（带重试，使用 SAVEPOINT 避免并发冲突时
            # 回滚同一事务中已创建的其他设备工单）
            for attempt in range(_MAX_RETRIES):
                wo_no = await generate_work_order_no(db)
                wo_data: dict[str, object] = {
                    "work_order_no": wo_no,
                    "equipment_id": eq_id,
                    "order_type": "计划维护",
                    "priority": "中",
                    "status": "待处理",
                    "reporter_id": None,  # 系统自动生成，无报修人
                    "maintenance_plan_id": plan.id,
                    "responsible_person_id": plan.executor_id,
                    "planned_start_date": plan.next_maintenance_date,
                    "original_equipment_status": equipment.status,
                }
                try:
                    async with db.begin_nested():
                        await repo.create_work_order(db, wo_data)
                    created_count += 1
                    any_created = True
                    logger.info(
                        "自动生成工单 %s (计划=%s, 设备=%s)",
                        wo_no,
                        plan.plan_name,
                        equipment.name,
                    )
                    break
                except IntegrityError:
                    if attempt < _MAX_RETRIES - 1:
                        continue
                    logger.error(
                        "维护计划 %s 工单号生成失败（重试 %d 次后放弃）",
                        plan.id,
                        _MAX_RETRIES,
                    )

        if any_created:
            # 更新 last_generated_date 防重
            plan.last_generated_date = plan.next_maintenance_date
            # 分类计划在此推进下次维护日期（设备计划由工单完成时推进）
            if plan.category_id and plan.next_maintenance_date:
                plan.next_maintenance_date = _calculate_next_maintenance_date(
                    plan.next_maintenance_date,
                    plan.frequency,
                    plan.frequency_unit,
                )
            await db.flush()
        else:
            skipped_count += 1

    return created_count, skipped_count

