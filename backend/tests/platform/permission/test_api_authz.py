"""权限管理 API 的鉴权边界：三项平台权限各自能走通哪些接口。

permission:role:manage 是总开关（恒包含其余两项）；permission:user:assign 可分配/移除
用户角色并查看；permission:user:view 只读。角色管理与切换用户视角对后两者必须保持 403。

覆盖业务场景：
- 只读用户：能看用户角色与有效权限；不能分配/移除、不能读角色目录
- 分配用户：能分配并移除角色、读角色目录；仍不能碰角色管理
- 角色管理与切换用户视角只认 permission:role:manage
- 管理角色：上述全部放行（总开关不被细分依赖漏掉）
- 无任何权限：全部 403
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import User
from app.platform.permission.models import Permission
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.service import PermissionService

BASE = "/api/v1/permission"
IMPERSONATE_START = "/api/v1/identity/impersonate/start"

MANAGE = "permission:role:manage"
ASSIGN = "permission:user:assign"
VIEW = "permission:user:view"

ApiFactory = Callable[[User, set[str]], AbstractAsyncContextManager[AsyncClient]]

_repo = PermissionRepository()
_service = PermissionService()


async def _grant_real_codes(
    db_session: AsyncSession, make_role, actor: User, codes: set[str],
) -> None:
    """给操作者真实授予权限码（范围守卫读数据库，不走门禁 patch）。"""
    perms = []
    for code in codes:
        perm = (
            await db_session.execute(
                select(Permission).where(Permission.code == code)
            )
        ).scalar_one_or_none()
        if perm is None:
            module, resource, action = code.split(":")
            perm = Permission(
                code=code, name=code, module=module,
                resource=resource, action=action,
            )
            db_session.add(perm)
            await db_session.flush()
        perms.append(perm)
    role = await make_role()
    await _repo.set_role_permissions(db_session, role.id, [p.id for p in perms])
    await _service.assign_role_to_user(db_session, actor.id, role.id)

# 角色管理的全部接口。载荷都是合法值，确保拦下来的是权限（403）而不是参数校验（422）；
# 删除角色排在最后，避免后续接口因角色已软删而 404。
_ROLE_ADMIN_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/permissions", None),
    ("POST", "/roles", {"code": "authz_probe_role", "name": "鉴权探针角色"}),
    ("PUT", "/roles/{role_id}", {"name": "鉴权探针改名"}),
    ("GET", "/roles/{role_id}/users", None),
    ("GET", "/roles/{role_id}/departments", None),
    ("POST", "/roles/{role_id}/departments", {"feishu_department_ids": ["odc-authz-probe"]}),
    ("DELETE", "/roles/{role_id}/departments/odc-authz-probe", None),
    ("DELETE", "/roles/{role_id}", None),
]


async def _request_role_admin_endpoints(
    ac: AsyncClient, role_id: object
) -> list[tuple[str, str, Response]]:
    """逐个请求角色管理接口，返回 (method, path, response)。"""
    results = []
    for method, path, body in _ROLE_ADMIN_ENDPOINTS:
        url = f"{BASE}{path.format(role_id=role_id)}"
        results.append((method, path, await ac.request(method, url, json=body)))
    return results


class TestUserViewReadOnly:
    async def test_can_read_user_permissions_and_roles(
        self, api: ApiFactory, make_user
    ) -> None:
        """只读用户能查看任意用户的角色与有效权限。"""
        viewer, target = await make_user(), await make_user()
        async with api(viewer, {VIEW}) as ac:
            perms = await ac.get(f"{BASE}/users/{target.id}/permissions")
            roles = await ac.get(f"{BASE}/users/{target.id}/roles")
        assert perms.status_code == 200, perms.text
        assert perms.json()["data"]["user_id"] == str(target.id)
        assert roles.status_code == 200, roles.text

    async def test_cannot_assign_or_remove_roles(
        self, api: ApiFactory, db_session: AsyncSession, make_user, make_role
    ) -> None:
        """只读用户分配/移除用户角色均 403，且不落任何分配记录。"""
        viewer, target = await make_user(), await make_user()
        role = await make_role()
        async with api(viewer, {VIEW}) as ac:
            assign = await ac.post(
                f"{BASE}/users/{target.id}/roles", json={"role_id": str(role.id)}
            )
            remove = await ac.delete(f"{BASE}/users/{target.id}/roles/{role.id}")
        assert assign.status_code == 403, assign.text
        assert remove.status_code == 403, remove.text
        assert await _repo.get_user_roles(db_session, target.id) == []

    async def test_cannot_read_role_catalog(self, api: ApiFactory, make_user) -> None:
        """只读用户读不了角色目录（只有分配角色时才用得上）。"""
        viewer = await make_user()
        async with api(viewer, {VIEW}) as ac:
            roles = await ac.get(f"{BASE}/roles")
        assert roles.status_code == 403, roles.text


class TestUserAssign:
    async def test_can_assign_then_remove_role(
        self, api: ApiFactory, db_session: AsyncSession, make_user, make_role
    ) -> None:
        """分配用户能读角色目录、给用户分配角色、看到分配结果，再移除。"""
        assigner, target = await make_user(), await make_user()
        role = await make_role()
        async with api(assigner, {ASSIGN}) as ac:
            catalog = await ac.get(f"{BASE}/roles")
            assigned = await ac.post(
                f"{BASE}/users/{target.id}/roles", json={"role_id": str(role.id)}
            )
            detail = await ac.get(f"{BASE}/users/{target.id}/permissions")
            removed = await ac.delete(f"{BASE}/users/{target.id}/roles/{role.id}")
        assert catalog.status_code == 200, catalog.text
        assert any(r["id"] == str(role.id) for r in catalog.json()["data"])
        assert assigned.status_code == 200, assigned.text
        assert detail.status_code == 200, detail.text
        assert [r["role_id"] for r in detail.json()["data"]["roles"]] == [str(role.id)]
        assert removed.status_code == 200, removed.text
        assert await _repo.get_user_roles(db_session, target.id) == []


class TestRoleManageAndImpersonation:
    @pytest.mark.parametrize("perms", [{VIEW}, {ASSIGN}], ids=["view", "assign"])
    async def test_role_endpoints_forbidden(
        self, api: ApiFactory, make_user, make_role, perms: set[str]
    ) -> None:
        """只读 / 分配用户访问全部角色管理接口均 403。"""
        user = await make_user()
        role = await make_role()
        async with api(user, perms) as ac:
            results = await _request_role_admin_endpoints(ac, role.id)
        for method, path, resp in results:
            assert resp.status_code == 403, f"{method} {path} → {resp.status_code} {resp.text}"

    @pytest.mark.parametrize("perms", [{VIEW}, {ASSIGN}], ids=["view", "assign"])
    async def test_impersonation_forbidden(
        self, api: ApiFactory, make_user, perms: set[str]
    ) -> None:
        """切换用户视角是以对方身份真实操作，不只读，故只认 permission:role:manage。"""
        user, target = await make_user(), await make_user()
        async with api(user, perms) as ac:
            resp = await ac.post(IMPERSONATE_START, json={"target_user_id": str(target.id)})
        assert resp.status_code == 403, resp.text

    async def test_manage_passes_everything(
        self, api: ApiFactory, db_session: AsyncSession, make_user, make_role
    ) -> None:
        """管理角色是总开关：用户权限的查看/分配、角色管理、切换视角全部放行。"""
        admin, target = await make_user(), await make_user()
        role = await make_role()
        async with api(admin, {MANAGE}) as ac:
            detail = await ac.get(f"{BASE}/users/{target.id}/permissions")
            roles = await ac.get(f"{BASE}/users/{target.id}/roles")
            assigned = await ac.post(
                f"{BASE}/users/{target.id}/roles", json={"role_id": str(role.id)}
            )
            removed = await ac.delete(f"{BASE}/users/{target.id}/roles/{role.id}")
            role_admin = await _request_role_admin_endpoints(ac, role.id)
            impersonate = await ac.post(
                IMPERSONATE_START, json={"target_user_id": str(target.id)}
            )
        assert detail.status_code == 200, detail.text
        assert roles.status_code == 200, roles.text
        assert assigned.status_code == 200, assigned.text
        assert removed.status_code == 200, removed.text
        assert await _repo.get_user_roles(db_session, target.id) == []
        for method, path, resp in role_admin:
            assert resp.status_code == 200, f"{method} {path} → {resp.status_code} {resp.text}"
        assert impersonate.status_code == 200, impersonate.text


class TestNoPermission:
    async def test_everything_forbidden(
        self, api: ApiFactory, make_user, make_role
    ) -> None:
        """不带任何权限的登录用户：用户权限、角色管理、切换视角全部 403。"""
        user, target = await make_user(), await make_user()
        role = await make_role()
        async with api(user, set()) as ac:
            detail = await ac.get(f"{BASE}/users/{target.id}/permissions")
            catalog = await ac.get(f"{BASE}/roles")
            assign = await ac.post(
                f"{BASE}/users/{target.id}/roles", json={"role_id": str(role.id)}
            )
            role_admin = await _request_role_admin_endpoints(ac, role.id)
            impersonate = await ac.post(
                IMPERSONATE_START, json={"target_user_id": str(target.id)}
            )
        for method, path, resp in [
            ("GET", "/users/{user_id}/permissions", detail),
            ("GET", "/roles", catalog),
            ("POST", "/users/{user_id}/roles", assign),
            *role_admin,
            ("POST", "impersonate/start", impersonate),
        ]:
            assert resp.status_code == 403, f"{method} {path} → {resp.status_code} {resp.text}"


class TestAssignCannotGrantRoleManage:
    """分配权限不能分发/移除含总开关的角色，否则 assign 用户可自我提权。"""

    async def _admin_role(self, db_session, make_role, make_permission):
        """含总开关权限的角色；权限码可能已被启动引导写入，先查后建。"""
        perm = (
            await db_session.execute(
                select(Permission).where(Permission.code == MANAGE)
            )
        ).scalar_one_or_none() or await make_permission(MANAGE, module="permission")
        role = await make_role(code="super_admin_probe")
        await _repo.set_role_permissions(db_session, role.id, [perm.id])
        return role

    async def test_cannot_assign_role_containing_role_manage(
        self, api: ApiFactory, db_session: AsyncSession,
        make_user, make_role, make_permission,
    ) -> None:
        """分配用户把超管角色发给自己 → 403，且不落分配记录。"""
        assigner = await make_user()
        admin_role = await self._admin_role(db_session, make_role, make_permission)
        async with api(assigner, {ASSIGN}) as ac:
            resp = await ac.post(
                f"{BASE}/users/{assigner.id}/roles", json={"role_id": str(admin_role.id)}
            )
        assert resp.status_code == 403, resp.text
        assert await _repo.get_user_roles(db_session, assigner.id) == []

    async def test_cannot_remove_role_containing_role_manage(
        self, api: ApiFactory, db_session: AsyncSession,
        make_user, make_role, make_permission,
    ) -> None:
        """分配用户不能移除别人的超管角色（防止把管理员锁在门外）。"""
        assigner, admin = await make_user(), await make_user()
        admin_role = await self._admin_role(db_session, make_role, make_permission)
        await _repo.assign_role_to_user(db_session, admin.id, admin_role.id)
        async with api(assigner, {ASSIGN}) as ac:
            resp = await ac.delete(f"{BASE}/users/{admin.id}/roles/{admin_role.id}")
        assert resp.status_code == 403, resp.text
        kept = [ur.role_id for ur in await _repo.get_user_roles(db_session, admin.id)]
        assert kept == [admin_role.id]

    async def test_manage_can_still_assign_admin_role(
        self, api: ApiFactory, db_session: AsyncSession,
        make_user, make_role, make_permission,
    ) -> None:
        """总开关用户照常可分发超管角色（拦截不能过度）。"""
        admin, target = await make_user(), await make_user()
        admin_role = await self._admin_role(db_session, make_role, make_permission)
        # 范围守卫读数据库：必须真实授予 role:manage，而不是只靠门禁的 patch
        await _grant_real_codes(db_session, make_role, admin, {MANAGE})
        async with api(admin, {MANAGE}) as ac:
            resp = await ac.post(
                f"{BASE}/users/{target.id}/roles", json={"role_id": str(admin_role.id)}
            )
        assert resp.status_code == 200, resp.text
