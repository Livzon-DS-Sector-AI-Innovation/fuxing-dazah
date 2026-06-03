"""设备模块公共API

其他模块可以通过此接口调用设备模块的功能。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment import service
from app.modules.equipment.schemas import EquipmentResponse, EquipmentStatus


async def get_equipment_by_id(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> EquipmentResponse:
    """获取设备信息（供其他模块调用）"""
    equipment = await service.get_equipment_by_id(db, equipment_id)
    return EquipmentResponse.model_validate(equipment)


async def get_equipments_by_category(
    db: AsyncSession,
    category_id: uuid.UUID,
) -> list[EquipmentResponse]:
    """获取指定分类的设备列表（供其他模块调用）"""
    equipments, _ = await service.get_equipments(db, category_id=category_id)
    return [EquipmentResponse.model_validate(e) for e in equipments]


async def get_equipments_by_location(
    db: AsyncSession,
    location_id: uuid.UUID,
) -> list[EquipmentResponse]:
    """获取指定位置的设备列表（供其他模块调用）"""
    equipments, _ = await service.get_equipments(db, location_id=location_id)
    return [EquipmentResponse.model_validate(e) for e in equipments]


async def update_equipment_status(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    status: EquipmentStatus,
) -> EquipmentResponse:
    """更新设备状态（供其他模块调用）"""
    from app.modules.equipment.schemas import EquipmentUpdate

    equipment = await service.update_equipment(
        db, equipment_id, EquipmentUpdate(status=status)
    )
    return EquipmentResponse.model_validate(equipment)
