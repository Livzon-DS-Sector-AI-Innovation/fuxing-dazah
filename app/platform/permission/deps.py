"""Permission FastAPI dependencies."""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException
from app.platform.identity.deps import CurrentUser
from app.platform.identity.models import User
from app.platform.permission.cache import (
    get_cached_permissions,
    set_cached_permissions,
)
from app.platform.permission.repository import PermissionRepository

_repo = PermissionRepository()


async def require_user(
    current_user: CurrentUser,
) -> User:
    """强制要求登录。替代可选的 CurrentUser。"""
    if current_user is None:
        raise AppException(status_code=401, message="未登录")
    return current_user


RequireUser = Annotated[User, Depends(require_user)]


async def get_user_permissions(user_id: str, db: AsyncSession) -> set[str]:
    """获取用户权限集合，优先从 Redis 缓存读取。"""
    cached = await get_cached_permissions(user_id)
    if cached is not None:
        return cached
    perms = await _repo.get_user_permission_codes(db, uuid.UUID(user_id))
    await set_cached_permissions(user_id, perms)
    return perms


def require_permission(*codes: str) -> Callable:
    """依赖注入工厂：要求用户拥有指定权限之一。

    用法: user = Depends(require_permission("equipment:inspection:create"))
    """

    async def checker(
        user: User = Depends(require_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user_perms = await get_user_permissions(str(user.id), db)
        if not set(codes) & user_perms:
            raise ForbiddenException(f"缺少权限: {', '.join(codes)}")
        return user

    return checker


async def require_admin(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求用户拥有 super_admin 角色。

    ADMIN_EMPLOYEE_NOS 仅用于启动引导（bootstrap），运行时以角色为准。
    超管可以移除其他超管的角色，被移除者立即失去管理权限。
    """
    user_perms = await get_user_permissions(str(user.id), db)
    if "permission:role:manage" in user_perms:
        return user
    raise ForbiddenException("仅管理员可操作")


RequireAdmin = Annotated[User, Depends(require_admin)]


async def apply_data_scope(
    query,  # sqlalchemy Select
    user: User,
    module: str,
    db: AsyncSession,
    model,  # ORM model class with created_by column
    resource: str | None = None,
):
    """根据用户角色在该模块的数据范围，自动注入 WHERE 过滤条件。

    resource 指定时仅计算拥有该 module+resource 权限的角色范围。
    """
    scope = await _repo.get_effective_data_scope(db, user.id, module, resource)

    if scope == "all":
        return query

    if scope == "self_only":
        return query.where(model.created_by == user.id)

    if scope == "department":
        dept_user_ids = await _get_department_user_ids(db, user.department)
        if dept_user_ids:
            return query.where(model.created_by.in_(dept_user_ids))
        return query.where(model.created_by == user.id)

    if scope == "department_and_children":
        dept_user_ids = await _get_department_tree_user_ids(db, user.department)
        if dept_user_ids:
            return query.where(model.created_by.in_(dept_user_ids))
        return query.where(model.created_by == user.id)

    return query


async def _get_department_user_ids(db: AsyncSession, department: str | None) -> list:
    """获取同部门所有用户 ID（按 department 字符串匹配）。"""
    if not department:
        return []
    stmt = select(User.id).where(
        User.department == department,
        User.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return list(result.scalars())


async def _get_department_tree_user_ids(
    db: AsyncSession, department: str | None
) -> list:
    """获取部门及所有下级部门的用户 ID。
    简化实现：按 department 名称前缀匹配。
    """
    if not department:
        return []
    stmt = select(User.id).where(
        or_(
            User.department == department,
            User.department.like(f"{department}/%"),
        ),
        User.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return list(result.scalars())
