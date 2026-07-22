"""设备模块的稳定公共接口。

其他模块如需查询设备信息，请通过此文件中的函数调用，不要直接 import
本模块的 service/repository/models。
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import build_access_context
from app.modules.equipment.models import Equipment
from app.modules.equipment.repository import equipment as equipment_repo
from app.platform.identity.models import User


@dataclass(frozen=True)
class EquipmentBrief:
    """设备摘要，供其他模块做存在性校验和快照。"""

    id: uuid.UUID
    equipment_no: str
    name: str


async def get_equipment_briefs(
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[EquipmentBrief]:
    """按 ID 批量获取未删除设备的摘要。不存在的 ID 缺失于结果，由调用方判断。"""
    if not ids:
        return []
    stmt = select(Equipment).where(
        Equipment.id.in_(ids),
        Equipment.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return [
        EquipmentBrief(id=e.id, equipment_no=e.equipment_no, name=e.name)
        for e in result.scalars()
    ]


async def list_equipments_for_user(
    db: AsyncSession,
    user: User,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EquipmentBrief], int]:
    """按调用用户的数据范围查询设备列表，返回 (设备摘要列表, 总数)。

    数据范围沿用设备台账（equipment:asset）的权限配置：
    超管看全部，其余按可见部门过滤，无权限用户仅返回空。
    """
    ctx = await build_access_context(db, user, resource="asset")
    equipments, total = await equipment_repo.get_equipments(
        db, ctx, status=status, keyword=keyword, page=page, page_size=page_size,
    )
    return [
        EquipmentBrief(id=e.id, equipment_no=e.equipment_no, name=e.name)
        for e in equipments
    ], total
