"""设备状态日志 repository：状态日志读写与开动率统计查询。"""

import uuid
from datetime import datetime

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, EquipmentStatusLog
from app.modules.equipment.service.data_scope import apply_equipment_scope


async def get_status_logs_by_equipment(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> list[EquipmentStatusLog]:
    """获取单台设备的状态变更历史（时间倒序）"""
    result = await db.execute(
        select(EquipmentStatusLog)
        .where(
            EquipmentStatusLog.equipment_id == equipment_id,
            EquipmentStatusLog.is_deleted == False,  # noqa: E712
        )
        .order_by(EquipmentStatusLog.changed_at.desc())
    )
    return list(result.scalars().all())


async def get_status_events_until(
    db: AsyncSession,
    equipment_ids: list[uuid.UUID],
    until: datetime,
    *,
    log_type: str = "status",
) -> dict[uuid.UUID, list[tuple[datetime, str]]]:
    """获取一批设备在 until 之前的全部指定类型状态事件（升序），按设备分组。

    ponytail: 状态切换是低频事件，全量取回内存分组即可；量级大了再改窗口聚合
    """
    if not equipment_ids:
        return {}
    result = await db.execute(
        select(
            EquipmentStatusLog.equipment_id,
            EquipmentStatusLog.changed_at,
            EquipmentStatusLog.new_status,
        )
        .where(
            EquipmentStatusLog.equipment_id.in_(equipment_ids),
            EquipmentStatusLog.log_type == log_type,
            EquipmentStatusLog.changed_at <= until,
            EquipmentStatusLog.is_deleted == False,  # noqa: E712
        )
        .order_by(EquipmentStatusLog.changed_at)
    )
    events: dict[uuid.UUID, list[tuple[datetime, str]]] = {}
    for eq_id, changed_at, new_status in result.all():
        events.setdefault(eq_id, []).append((changed_at, new_status))
    return events


async def get_equipments_for_availability(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
) -> list[Row[tuple[uuid.UUID, str, str, str, str]]]:
    """获取数据范围内的设备简要行（id/编号/名称/设备状态/运行状态）；报废设备不参与开动率"""
    query = (
        select(
            Equipment.id,
            Equipment.equipment_no,
            Equipment.name,
            Equipment.status,
            Equipment.running_status,
        )
        .where(
            Equipment.is_deleted == False,  # noqa: E712
            Equipment.status != "报废",
        )
        .order_by(Equipment.equipment_no)
    )
    query = apply_equipment_scope(query, ctx, Equipment.department_id, "department_id")
    result = await db.execute(query)
    return list(result.all())
