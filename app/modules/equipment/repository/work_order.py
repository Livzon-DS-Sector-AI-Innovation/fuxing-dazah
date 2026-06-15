"""Work order repository functions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models import WorkOrder


async def create_work_order(
    db: AsyncSession,
    data: dict[str, Any],
) -> WorkOrder:
    """创建工单"""
    work_order = WorkOrder(**data)
    db.add(work_order)
    await db.flush()
    return work_order


async def get_work_order_by_id(
    db: AsyncSession,
    work_order_id: uuid.UUID,
) -> WorkOrder | None:
    """根据ID获取工单"""
    result = await db.execute(
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.reporter),
            selectinload(WorkOrder.assignee),
            selectinload(WorkOrder.responsible_person),
            selectinload(WorkOrder.equipment),
            selectinload(WorkOrder.fault_symptom),
            selectinload(WorkOrder.fault_cause),
            selectinload(WorkOrder.fault_action),
            selectinload(WorkOrder.images),
        )
        .where(
            WorkOrder.id == work_order_id,
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_max_work_order_no(db: AsyncSession) -> str | None:
    """获取当天最大工单号"""
    today = datetime.now().strftime("%Y%m%d")
    pattern = f"WO-{today}-%"
    result = await db.execute(
        select(WorkOrder.work_order_no)
        .where(
            WorkOrder.work_order_no.like(pattern),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
        .order_by(WorkOrder.work_order_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_open_work_orders_by_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> int:
    """统计设备未关闭的工单数"""
    result = await db.execute(
        select(func.count())
        .select_from(WorkOrder)
        .where(
            WorkOrder.equipment_id == equipment_id,
            WorkOrder.status.notin_(["已完成", "已关闭"]),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar() or 0


async def get_work_orders(
    db: AsyncSession,
    status: str | None = None,
    equipment_id: uuid.UUID | None = None,
    priority: str | None = None,
    order_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WorkOrder], int]:
    """获取工单列表"""
    query = (
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.reporter),
            selectinload(WorkOrder.assignee),
            selectinload(WorkOrder.responsible_person),
            selectinload(WorkOrder.equipment),
            selectinload(WorkOrder.fault_symptom),
            selectinload(WorkOrder.fault_cause),
            selectinload(WorkOrder.fault_action),
            selectinload(WorkOrder.images),
        )
        .where(WorkOrder.is_deleted == False)  # noqa: E712
    )

    if status:
        query = query.where(WorkOrder.status == status)
    if equipment_id:
        query = query.where(WorkOrder.equipment_id == equipment_id)
    if priority:
        query = query.where(WorkOrder.priority == priority)
    if order_type:
        query = query.where(WorkOrder.order_type == order_type)

    count_query = select(func.count()).select_from(
        query.with_only_columns(WorkOrder.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(WorkOrder.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_work_order_statistics(db: AsyncSession) -> dict[str, Any]:
    """获取工单统计"""
    total_result = await db.execute(
        select(func.count()).where(WorkOrder.is_deleted == False)  # noqa: E712
    )
    total = total_result.scalar() or 0

    status_result = await db.execute(
        select(WorkOrder.status, func.count())
        .where(WorkOrder.is_deleted == False)  # noqa: E712
        .group_by(WorkOrder.status)
    )
    by_status = {row[0]: row[1] for row in status_result.all()}

    type_result = await db.execute(
        select(WorkOrder.order_type, func.count())
        .where(WorkOrder.is_deleted == False)  # noqa: E712
        .group_by(WorkOrder.order_type)
    )
    by_type = {row[0]: row[1] for row in type_result.all()}

    priority_result = await db.execute(
        select(WorkOrder.priority, func.count())
        .where(WorkOrder.is_deleted == False)  # noqa: E712
        .group_by(WorkOrder.priority)
    )
    by_priority = {row[0]: row[1] for row in priority_result.all()}

    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "by_priority": by_priority,
    }


async def create_material_consumption(
    db: AsyncSession,
    data: dict[str, Any],
) -> "SparePartTransaction":  # noqa: F821
    """创建领料记录"""
    from app.modules.equipment.models.spare_part import SparePartTransaction

    transaction = SparePartTransaction(**data)
    db.add(transaction)
    await db.flush()
    return transaction


async def get_material_consumptions(
    db: AsyncSession,
    work_order_id: uuid.UUID,
) -> list["SparePartTransaction"]:  # noqa: F821
    """获取工单领料记录"""
    from app.modules.equipment.models.spare_part import SparePartTransaction

    result = await db.execute(
        select(SparePartTransaction)
        .where(
            SparePartTransaction.work_order_id == work_order_id,
            SparePartTransaction.is_deleted == False,  # noqa: E712
        )
        .order_by(SparePartTransaction.created_at.desc())
    )
    return list(result.scalars().all())


async def exists_unclosed_work_order(
    db: AsyncSession, task_id: uuid.UUID, equipment_id: uuid.UUID
) -> bool:
    """检查某巡检任务+设备是否已有未关闭工单"""
    result = await db.execute(
        select(func.count())
        .select_from(WorkOrder)
        .where(
            WorkOrder.inspection_task_id == task_id,
            WorkOrder.equipment_id == equipment_id,
            WorkOrder.status.notin_(["已完成", "已关闭"]),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )
    return (result.scalar() or 0) > 0


async def get_pending_work_orders_by_inspection_task(
    db: AsyncSession, task_id: uuid.UUID
) -> list[WorkOrder]:
    """查询某巡检任务关联的未处理工单（状态非已完成/已关闭）"""
    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.equipment))
        .where(
            WorkOrder.inspection_task_id == task_id,
            WorkOrder.status.notin_(["已完成", "已关闭"]),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
        .order_by(WorkOrder.created_at)
    )
    return list(result.scalars().all())


async def get_user_work_orders(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[WorkOrder]:
    """查询用户的未关闭工单（指派给我的 + 我是责任人的）"""
    from sqlalchemy import or_

    result = await db.execute(
        select(WorkOrder)
        .options(selectinload(WorkOrder.equipment))
        .where(
            or_(
                WorkOrder.assignee_id == user_id,
                WorkOrder.responsible_person_id == user_id,
            ),
            WorkOrder.status.notin_(["已完成", "已关闭"]),
            WorkOrder.is_deleted == False,  # noqa: E712
        )
        .order_by(WorkOrder.created_at.desc())
    )
    return list(result.scalars().all())


async def get_work_order_by_no(
    db: AsyncSession,
    work_order_no: str,
) -> WorkOrder | None:
    """根据工单号精确查找工单"""
    result = await db.execute(
        select(WorkOrder)
        .options(
            selectinload(WorkOrder.reporter),
            selectinload(WorkOrder.assignee),
            selectinload(WorkOrder.responsible_person),
            selectinload(WorkOrder.equipment),
            selectinload(WorkOrder.fault_symptom),
            selectinload(WorkOrder.fault_cause),
            selectinload(WorkOrder.fault_action),
            selectinload(WorkOrder.images),
        )
        .where(
            WorkOrder.work_order_no == work_order_no,
            WorkOrder.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()
