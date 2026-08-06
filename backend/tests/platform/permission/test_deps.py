"""权限依赖校验业务测试（require_permission / require_admin / require_user）。

覆盖业务场景：
- 未登录访问权限接口被拒（require_user）
- 缺少权限时 require_permission 抛 ForbiddenException
- 拥有任一目标权限时校验通过
- 多权限码满足其一即可
- require_admin 要求 permission:role:manage 权限
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.platform.identity.models import User
from app.platform.permission.deps import (
    require_admin,
    require_permission,
    require_user,
)
from app.platform.permission.models import Permission, Role
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.service import PermissionService

_repo = PermissionRepository()
_service = PermissionService()


async def _grant_user_permission(
    db: AsyncSession, make_permission, make_role, make_user,
) -> tuple[Permission, Role, User]:
    """创建 权限+角色+用户 并完成分配，返回 (perm, role, user)。"""
    perm = await make_permission()
    role = await make_role()
    await _repo.set_role_permissions(db, role.id, [perm.id])
    user = await make_user()
    await _service.assign_role_to_user(db, user.id, role.id)
    return perm, role, user


class TestRequireUser:
    async def test_unauthenticated_rejected(self) -> None:
        """未登录（None）时抛 401 AppException。"""
        with pytest.raises(AppException, match="未登录"):
            await require_user(None)


class TestRequirePermission:
    async def test_denied_without_permission(
        self, db_session: AsyncSession, make_user,
    ) -> None:
        """用户无任何权限时 require_permission 抛 ForbiddenException。"""
        user = await make_user()
        checker = require_permission("equipment:inspection:create")
        with pytest.raises(ForbiddenException, match="缺少权限"):
            await checker(user=user, db=db_session)

    async def test_passes_with_permission(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """用户拥有目标权限时校验通过并返回用户。"""
        perm, _, user = await _grant_user_permission(
            db_session, make_permission, make_role, make_user,
        )
        checker = require_permission(perm.code)
        result = await checker(user=user, db=db_session)
        assert result.id == user.id

    async def test_any_of_multiple_codes(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """require_permission 多码满足其一即可通过。"""
        perm, _, user = await _grant_user_permission(
            db_session, make_permission, make_role, make_user,
        )
        checker = require_permission(
            "equipment:nonexistent:create", perm.code,
        )
        result = await checker(user=user, db=db_session)
        assert result.id == user.id

    async def test_admin_cannot_bypass(
        self, db_session: AsyncSession,
        make_permission, make_role, make_user,
    ) -> None:
        """拥有其他权限（非目标码）仍被拒绝。"""
        _, _, user = await _grant_user_permission(
            db_session, make_permission, make_role, make_user,
        )
        checker = require_permission("safety:audit:approve")
        with pytest.raises(ForbiddenException):
            await checker(user=user, db=db_session)


class TestRequireAdmin:
    async def test_admin_requires_manage_permission(
        self, db_session: AsyncSession,
        make_role, make_user,
    ) -> None:
        """拥有 permission:role:manage 权限的用户通过管理员校验。"""
        from sqlalchemy import select

        from app.platform.permission.models import Permission

        # 真实库 bootstrap 可能已同步该权限，存在则复用，否则创建
        stmt = select(Permission).where(
            Permission.code == "permission:role:manage",
        )
        perm = (await db_session.execute(stmt)).scalar_one_or_none()
        if perm is None:
            perm = Permission(
                code="permission:role:manage",
                name="管理角色",
                module="permission",
                resource="role",
                action="manage",
            )
            db_session.add(perm)
            await db_session.flush()

        role = await make_role()
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        user = await make_user()
        await _service.assign_role_to_user(db_session, user.id, role.id)

        result = await require_admin(user=user, db=db_session)
        assert result.id == user.id

    async def test_non_admin_rejected(
        self, db_session: AsyncSession, make_user,
    ) -> None:
        """无管理权限的用户抛 ForbiddenException。"""
        user = await make_user()
        with pytest.raises(ForbiddenException, match="仅管理员"):
            await require_admin(user=user, db=db_session)
