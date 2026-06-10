"""设备模块公共API

其他模块可以通过此接口调用设备模块的功能。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment import service
from app.modules.equipment.schemas import EquipmentResponse, EquipmentStatus
from app.modules.equipment.schemas.personnel import (
    CandidateResponse,
    PersonnelResponse,
    RoleResponse,
)


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
    result = []
    for e in equipments:
        resp = EquipmentResponse.model_validate(e)
        links = getattr(e, "category_links", []) or []
        resp.category_ids = [link.category_id for link in links if not link.is_deleted]
        names = [link.category.name for link in links if not link.is_deleted and link.category]
        resp.category_names = "、".join(names) if names else None
        result.append(resp)
    return result


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


# ── 人员配置公共接口 ──

async def get_personnel_by_id(
    db: AsyncSession,
    personnel_id: uuid.UUID,
) -> PersonnelResponse | None:
    """获取设备人员信息（供其他模块调用）"""
    from app.modules.equipment.service.personnel import (
        get_personnel_by_id as _get,
    )
    return await _get(db, personnel_id)


async def list_personnel(
    db: AsyncSession,
    role_codes: list[str] | None = None,
    is_active: bool | None = None,
) -> list[PersonnelResponse]:
    """获取设备人员列表（供其他模块调用）"""
    role_ids = None
    if role_codes:
        role_ids = []
        for code in role_codes:
            role = await service.get_role_by_code(db, code)
            if role:
                role_ids.append(role.id)
    result = await service.list_personnel(
        db, role_ids=role_ids, is_active=is_active, page_size=500,
    )
    return result.items


async def get_candidates(
    db: AsyncSession,
    role_codes: list[str],
    category_id: uuid.UUID | None = None,
) -> list[CandidateResponse]:
    """按角色查找可分配人员（供其他模块调用）"""
    from app.modules.equipment.service.personnel import (
        get_candidates as _get,
    )
    return await _get(db, role_codes, category_id=category_id)


async def list_roles(
    db: AsyncSession,
    scope: str | None = None,
) -> list[RoleResponse]:
    """获取角色列表（供其他模块调用）"""
    roles, _ = await service.list_roles(db, scope=scope)
    return roles


async def get_role_by_code(db: AsyncSession, code: str) -> RoleResponse | None:
    """按编码查角色（供其他模块调用）"""
    return await service.get_role_by_code(db, code)
