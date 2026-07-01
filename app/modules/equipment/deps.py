"""设备模块组合式访问依赖。

将权限检查 + 数据范围解析打包为 EquipmentAccessContext，
供 API 端点、Service、Repository 统一使用。
"""

import uuid
from dataclasses import dataclass, field

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission
from app.platform.permission.repository import PermissionRepository

_perm_repo = PermissionRepository()


@dataclass
class EquipmentAccessContext:
    """设备模块访问上下文——包含用户信息和数据范围。"""

    user: User
    data_scope: str  # "all" | "department" | "department_and_children" | "self_only"
    department_user_ids: list[uuid.UUID] = field(default_factory=list)
    visible_department_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def is_unrestricted(self) -> bool:
        """是否为全量数据范围（超管）。"""
        return self.data_scope == "all"


async def _resolve_department_user_ids(
    db: AsyncSession, user: User, scope: str
) -> list[uuid.UUID]:
    """根据数据范围获取可见部门下的所有用户 ID。"""
    department = user.department
    if not department:
        return [user.id]

    if scope == "self_only":
        return [user.id]

    if scope == "department":
        stmt = select(User.id).where(
            User.department == department,
            User.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    if scope == "department_and_children":
        stmt = select(User.id).where(
            or_(
                User.department == department,
                User.department.like(f"{department}/%"),
            ),
            User.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    return []


async def _resolve_visible_department_ids(
    db: AsyncSession, user: User, scope: str
) -> list[uuid.UUID]:
    """根据数据范围获取可见部门的 ID 列表（用于 Equipment.department_id 过滤）。

    Equipment.department_id 逻辑引用 identity.departments.id (UUID)。
    User.department 是斜杠分隔的部门路径字符串（如 "总部/生产部/车间A"）。
    Department.name 是叶子部门名称，Department.path 是 JSON 数组。

    策略：通过 Department.name 匹配用户路径中的叶子部门名称，
    对于 department_and_children 额外通过 parent_feishu_department_id 向下遍历。
    """
    from app.platform.identity.models import Department

    department = user.department
    if not department:
        return []

    if scope == "self_only":
        return []

    # 提取叶子部门名称
    leaf_name = department.rsplit("/", 1)[-1]

    if scope == "department":
        # 精确匹配叶子部门名称
        stmt = select(Department.id).where(
            Department.name == leaf_name,
            Department.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return list(result.scalars())

    if scope == "department_and_children":
        # 匹配叶子部门 + 其所有子部门（通过 parent 关系向下遍历）
        stmt = select(Department).where(
            Department.name == leaf_name,
            Department.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        matched_depts = list(result.scalars())

        if not matched_depts:
            return []

        dept_ids: list[uuid.UUID] = [d.id for d in matched_depts]
        feishu_ids = [d.feishu_department_id for d in matched_depts]

        # 向下遍历子部门（最多 5 层）
        for _ in range(5):
            child_stmt = select(Department).where(
                Department.parent_feishu_department_id.in_(feishu_ids),
                Department.is_deleted == False,  # noqa: E712
            )
            child_result = await db.execute(child_stmt)
            children = list(child_result.scalars())
            if not children:
                break
            dept_ids.extend(c.id for c in children)
            feishu_ids = [c.feishu_department_id for c in children]

        return dept_ids

    return []


def require_equipment_access(*codes: str):
    """组合依赖工厂：权限检查 + 数据范围解析。

    用法:
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:asset:read")
        )
    """
    perm_dep = require_permission(*codes)

    async def _dependency(
        user: User = Depends(perm_dep),
        db: AsyncSession = Depends(get_db),
    ) -> EquipmentAccessContext:
        scope = await _perm_repo.get_effective_data_scope(db, user.id, "equipment")
        dept_user_ids = await _resolve_department_user_ids(db, user, scope)
        visible_dept_ids = await _resolve_visible_department_ids(db, user, scope)
        return EquipmentAccessContext(
            user=user,
            data_scope=scope,
            department_user_ids=dept_user_ids,
            visible_department_ids=visible_dept_ids,
        )

    return _dependency
