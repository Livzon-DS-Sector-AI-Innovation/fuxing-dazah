"""委派式角色管理的范围边界：权限码 ⊆ 自身、数据范围不宽于自身。

`api` 夹具只 patch 端点门禁用的 `deps.get_user_permissions`；
范围守卫直接读数据库，所以每个用例都给操作者真实授予角色/权限。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import User
from app.platform.permission.models import Permission, Role
from app.platform.permission.repository import PermissionRepository
from app.platform.permission.service import PermissionService

BASE = "/api/v1/permission"

MANAGE = "permission:role:manage"
DELEGATE = "permission:role:delegate"
ASSIGN = "permission:user:assign"
OWN_CODE = "qa:coa:read"
FOREIGN_CODE = "equipment:workorder:create"

ApiFactory = Callable[[User, set[str]], AbstractAsyncContextManager[AsyncClient]]
_repo = PermissionRepository()
_service = PermissionService()


def _role_code(prefix: str = "probe") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _perm(db: AsyncSession, code: str) -> Permission:
    """按 code 取/建权限行（注册表可能已同步）。"""
    perm = (
        await db.execute(select(Permission).where(Permission.code == code))
    ).scalar_one_or_none()
    if perm is None:
        module, resource, action = code.split(":")
        perm = Permission(
            code=code, name=f"权限{code}", module=module,
            resource=resource, action=action,
        )
        db.add(perm)
        await db.flush()
    return perm


async def _actor_with_scope(
    db: AsyncSession,
    make_user,
    make_role,
    *,
    codes: set[str],
    data_scope: str = "department",
) -> User:
    """给操作者真实授予 codes（含 delegate/assign/manage 本身），统一数据范围。"""
    actor = await make_user()
    perms = [await _perm(db, code) for code in codes]
    role = await make_role(data_scope=data_scope)
    await _repo.set_role_permissions(db, role.id, [p.id for p in perms])
    await _service.assign_role_to_user(db, actor.id, role.id)
    return actor


async def _role_with(
    db: AsyncSession,
    make_role,
    *,
    codes: set[str],
    data_scope: str = "department",
    overrides: dict[str, str] | None = None,
) -> Role:
    """直接建角色（绕过 API），用于「当前状态」检查。"""
    role = await make_role(data_scope=data_scope)
    perms = [await _perm(db, code) for code in codes]
    await _repo.set_role_permissions(db, role.id, [p.id for p in perms])
    if overrides:
        await _repo.set_role_data_scope_overrides(db, role.id, overrides)
    return role


async def test_delegate_creates_role_within_scope(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """权限码与数据范围都在自身内 → 200；零权限角色也不崩。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    own = await _perm(db_session, OWN_CODE)
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        within = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "范围内角色",
                "data_scope": "department", "permission_ids": [str(own.id)],
            },
        )
        empty = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "空角色",
                "data_scope": "department", "permission_ids": [],
            },
        )
    assert within.status_code == 200, within.text
    assert empty.status_code == 200, empty.text


async def test_delegate_cannot_create_foreign_code(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """角色含操作者没有的权限码 → 403。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    foreign = await _perm(db_session, FOREIGN_CODE)
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "越权角色",
                "data_scope": "department", "permission_ids": [str(foreign.id)],
            },
        )
    assert resp.status_code == 403, resp.text


async def test_delegate_cannot_create_wider_scope(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """操作者 qa:coa 范围 department，角色 data_scope=all → 403。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    own = await _perm(db_session, OWN_CODE)
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "宽范围角色",
                "data_scope": "all", "permission_ids": [str(own.id)],
            },
        )
    assert resp.status_code == 403, resp.text


async def test_delegate_override_must_fit(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """模块覆盖值超出自身范围 → 403；等于自身 → 200。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    own = await _perm(db_session, OWN_CODE)
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        wider = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "覆盖越界",
                "data_scope": "department",
                "data_scope_overrides": {"qa": "all"},
                "permission_ids": [str(own.id)],
            },
        )
        equal = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "覆盖合法",
                "data_scope": "department",
                "data_scope_overrides": {"qa": "self_only"},
                "permission_ids": [str(own.id)],
            },
        )
    assert wider.status_code == 403, wider.text
    assert equal.status_code == 200, equal.text


async def test_delegate_cannot_update_role_with_foreign_codes(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """当前角色含外码 → 403（即使只改名字/缩回）。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    target = await _role_with(db_session, make_role, codes={FOREIGN_CODE})
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.put(
            f"{BASE}/roles/{target.id}", json={"name": "改名尝试"}
        )
    assert resp.status_code == 403, resp.text


async def test_delegate_cannot_update_role_with_wider_scope(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """当前角色码在内但数据范围更宽 → 403。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    target = await _role_with(
        db_session, make_role, codes={OWN_CODE}, data_scope="all",
    )
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.put(
            f"{BASE}/roles/{target.id}", json={"name": "改名尝试"}
        )
    assert resp.status_code == 403, resp.text


async def test_delegate_delete_within_and_outside(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """范围内角色可删；范围外 403。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    within = await _role_with(db_session, make_role, codes={OWN_CODE})
    outside = await _role_with(db_session, make_role, codes={FOREIGN_CODE})
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        ok = await ac.delete(f"{BASE}/roles/{within.id}")
        denied = await ac.delete(f"{BASE}/roles/{outside.id}")
    assert ok.status_code == 200, ok.text
    assert denied.status_code == 403, denied.text


async def test_user_assign_boundaries(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """assign：外码 403、范围更宽 403、范围内 200。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={ASSIGN, OWN_CODE},
    )
    target = await make_user()
    foreign = await _role_with(db_session, make_role, codes={FOREIGN_CODE})
    wider = await _role_with(
        db_session, make_role, codes={OWN_CODE}, data_scope="all",
    )
    within = await _role_with(db_session, make_role, codes={OWN_CODE})
    async with api(actor, {ASSIGN, OWN_CODE}) as ac:
        denied_foreign = await ac.post(
            f"{BASE}/users/{target.id}/roles",
            json={"role_id": str(foreign.id)},
        )
        denied_wider = await ac.post(
            f"{BASE}/users/{target.id}/roles",
            json={"role_id": str(wider.id)},
        )
        ok = await ac.post(
            f"{BASE}/users/{target.id}/roles",
            json={"role_id": str(within.id)},
        )
    assert denied_foreign.status_code == 403, denied_foreign.text
    assert denied_wider.status_code == 403, denied_wider.text
    assert ok.status_code == 200, ok.text


async def test_full_admin_bypasses_scope(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """role:manage 全权：外码 + all 范围也能建。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={MANAGE, OWN_CODE},
    )
    foreign = await _perm(db_session, FOREIGN_CODE)
    async with api(actor, {MANAGE, OWN_CODE}) as ac:
        resp = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "全权角色",
                "data_scope": "all", "permission_ids": [str(foreign.id)],
            },
        )
    assert resp.status_code == 200, resp.text


async def test_delegate_role_list_filtered_by_codes(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """delegate 的 /roles 只返回码子集角色；manage 看到全部。"""
    delegate = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    admin = await _actor_with_scope(
        db_session, make_user, make_role, codes={MANAGE, OWN_CODE},
    )
    within = await _role_with(db_session, make_role, codes={OWN_CODE})
    outside = await _role_with(db_session, make_role, codes={FOREIGN_CODE})
    async with api(delegate, {DELEGATE, OWN_CODE}) as ac:
        data = (await ac.get(f"{BASE}/roles")).json()["data"]
    ids = {r["id"] for r in data}
    assert str(within.id) in ids
    assert str(outside.id) not in ids
    async with api(admin, {MANAGE, OWN_CODE}) as ac:
        admin_ids = {
            r["id"] for r in (await ac.get(f"{BASE}/roles")).json()["data"]
        }
    assert str(outside.id) in admin_ids


async def test_department_assign_boundaries(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """部门分配：范围内 200、范围外 403。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    within = await _role_with(db_session, make_role, codes={OWN_CODE})
    outside = await _role_with(db_session, make_role, codes={FOREIGN_CODE})
    payload = {"feishu_department_ids": ["odc_probe"]}
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        ok = await ac.post(
            f"{BASE}/roles/{within.id}/departments", json=payload
        )
        denied = await ac.post(
            f"{BASE}/roles/{outside.id}/departments", json=payload
        )
    assert ok.status_code == 200, ok.text
    assert denied.status_code == 403, denied.text


async def test_unknown_permission_id_rejected(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """提交不存在的权限 id → 400。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "坏 id",
                "data_scope": "department",
                "permission_ids": [str(uuid.uuid4())],
            },
        )
    assert resp.status_code == 400, resp.text


async def test_unknown_permission_id_rejected_for_admin(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """全权用户也不能写入不存在的权限 id（存在性校验对所有人生效）。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={MANAGE, OWN_CODE},
    )
    async with api(actor, {MANAGE, OWN_CODE}) as ac:
        resp = await ac.post(
            f"{BASE}/roles",
            json={
                "code": _role_code(), "name": "坏 id",
                "data_scope": "all",
                "permission_ids": [str(uuid.uuid4())],
            },
        )
    assert resp.status_code == 400, resp.text


async def test_soft_deleted_permission_does_not_block_edit(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """角色含软删除权限 id：未删部分在范围内时仍可编辑。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    retired = await _perm(db_session, f"qa:retired:{uuid.uuid4().hex[:6]}")
    retired.is_deleted = True
    await db_session.flush()
    own = await _perm(db_session, OWN_CODE)
    target = await make_role()
    await _repo.set_role_permissions(
        db_session, target.id, [own.id, retired.id]
    )
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        resp = await ac.put(
            f"{BASE}/roles/{target.id}", json={"name": "保留旧码改名"}
        )
    assert resp.status_code == 200, resp.text


async def test_delegate_cannot_read_user_permissions_but_can_assign(
    api: ApiFactory, db_session: AsyncSession, make_user, make_role,
) -> None:
    """2B：delegate 不可读用户权限页（403），但可分配范围内角色（200）。"""
    actor = await _actor_with_scope(
        db_session, make_user, make_role, codes={DELEGATE, OWN_CODE},
    )
    target = await make_user()
    within = await _role_with(db_session, make_role, codes={OWN_CODE})
    async with api(actor, {DELEGATE, OWN_CODE}) as ac:
        read = await ac.get(f"{BASE}/users/{target.id}/permissions")
        assign = await ac.post(
            f"{BASE}/users/{target.id}/roles",
            json={"role_id": str(within.id)},
        )
    assert read.status_code == 403, read.text
    assert assign.status_code == 200, assign.text
