"""设备模块的稳定公共接口。

其他模块如需查询设备信息，请通过此文件中的函数调用，不要直接 import
本模块的 service/repository/models。
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import build_access_context
from app.modules.equipment.models import Equipment
from app.modules.equipment.repository import equipment as equipment_repo
from app.modules.equipment.service.data_scope import apply_equipment_scope
from app.platform.identity.models import Department, User

# 设备状态里的终态；报废设备不应再被其他模块引用为可用来源。
EQUIPMENT_SCRAPPED_STATUS = "报废"


@dataclass(frozen=True)
class EquipmentBrief:
    """设备摘要，供其他模块做存在性校验和快照。"""

    id: uuid.UUID
    equipment_no: str
    name: str
    is_deleted: bool = False
    status: str | None = None

    @property
    def code(self) -> str:
        """跨模块统一的编码别名。"""
        return self.equipment_no

    @property
    def equipment_code(self) -> str:
        """兼容设备台账常用的编码命名。"""
        return self.equipment_no

    @property
    def equipment_name(self) -> str:
        """兼容设备台账常用的名称命名。"""
        return self.name

    @property
    def is_active(self) -> bool:
        """设备是否可被其他模块引用：未软删除且未报废。

        只判断 ``is_deleted`` 会把报废设备算作可用来源，因此这里一并排除
        「报废」；``status`` 未取到的调用方退化为原来的软删除口径。
        """
        return not self.is_deleted and self.status != EQUIPMENT_SCRAPPED_STATUS


async def get_equipment_briefs(
    db: AsyncSession,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
    *,
    include_deleted: bool = False,
) -> list[EquipmentBrief]:
    """按 ID 批量获取设备摘要。

    默认只返回未软删除设备；不存在的 ID 会从结果中省略。设备模块原有
    调用方只传两个位置参数，新增的 ``include_deleted`` 为向后兼容的关键字
    选项。
    """
    if ids is None:
        return []
    raw_ids: Sequence[uuid.UUID | str]
    if isinstance(ids, (uuid.UUID, str)):
        raw_ids = [ids]
    else:
        raw_ids = ids
    normalized_ids: list[uuid.UUID] = []
    for value in raw_ids:
        if isinstance(value, uuid.UUID):
            normalized_ids.append(value)
        elif isinstance(value, str):
            try:
                normalized_ids.append(uuid.UUID(value))
            except ValueError:
                continue
    if not normalized_ids:
        return []
    stmt = select(Equipment).where(Equipment.id.in_(normalized_ids))
    if not include_deleted:
        stmt = stmt.where(Equipment.is_deleted == False)  # noqa: E712
    result = await db.execute(stmt)
    by_id = {
        e.id: EquipmentBrief(
            id=e.id,
            equipment_no=e.equipment_no,
            name=e.name,
            is_deleted=bool(getattr(e, "is_deleted", False)),
            status=getattr(e, "status", None),
        )
        for e in result.scalars()
    }
    # 保持输入 ID 顺序并去重；对引用校验调用方更友好。
    briefs: list[EquipmentBrief] = []
    seen: set[uuid.UUID] = set()
    for equipment_id in normalized_ids:
        if equipment_id in seen:
            continue
        seen.add(equipment_id)
        brief = by_id.get(equipment_id)
        if brief is not None:
            briefs.append(brief)
    return briefs


async def get_equipment_brief(
    db: AsyncSession,
    equipment_id: uuid.UUID | str,
    *,
    include_deleted: bool = False,
) -> EquipmentBrief | None:
    """按 ID 获取单个设备摘要。"""
    rows = await get_equipment_briefs(
        db,
        [equipment_id],
        include_deleted=include_deleted,
    )
    return rows[0] if rows else None


# ``*_by_ids`` 是跨模块调用中常见的命名，作为稳定别名保留。
get_equipment_by_ids = get_equipment_briefs


async def get_equipment_briefs_for_user(
    db: AsyncSession, user: User, ids: list[uuid.UUID],
) -> list[EquipmentBrief]:
    """按 ID 批量获取设备摘要，按调用用户的数据范围过滤（设备台账口径）。

    不在用户可见范围内的 ID 缺失于结果，由调用方判断。
    """
    if not ids:
        return []
    ctx = await build_access_context(db, user, resource="asset")
    stmt = select(Equipment).where(
        Equipment.id.in_(ids),
        Equipment.is_deleted == False,  # noqa: E712
    )
    stmt = apply_equipment_scope(stmt, ctx, Equipment.department_id, "department_id")
    result = await db.execute(stmt)
    return [
        EquipmentBrief(
            id=e.id,
            equipment_no=e.equipment_no,
            name=e.name,
            status=getattr(e, "status", None),
        )
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
        EquipmentBrief(
            id=e.id,
            equipment_no=e.equipment_no,
            name=e.name,
            is_deleted=bool(getattr(e, "is_deleted", False)),
            status=getattr(e, "status", None),
        )
        for e in equipments
    ], total


@dataclass(frozen=True)
class EquipmentDeptBrief:
    """设备部门摘要：编号、名称、归属部门。"""

    equipment_no: str
    name: str
    department_name: str


async def list_all_equipment_dept(
    db: AsyncSession,
) -> list[EquipmentDeptBrief]:
    """获取所有未删除设备的编号、名称、归属部门名称。"""
    stmt = (
        select(
            Equipment.equipment_no,
            Equipment.name,
            Department.name.label("department_name"),
        )
        .outerjoin(Department, Equipment.department_id == Department.id)
        .where(Equipment.is_deleted == False)  # noqa: E712
        .order_by(Equipment.equipment_no)
    )
    result = await db.execute(stmt)
    return [
        EquipmentDeptBrief(
            equipment_no=row.equipment_no,
            name=row.name,
            department_name=row.department_name or "",
        )
        for row in result
    ]


__all__ = [
    "EquipmentBrief",
    "EquipmentDeptBrief",
    "get_equipment_briefs",
    "get_equipment_brief",
    "get_equipment_by_ids",
    "get_equipment_briefs_for_user",
    "list_equipments_for_user",
    "list_all_equipment_dept",
]
