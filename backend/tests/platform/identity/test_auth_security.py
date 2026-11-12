"""认证安全测试：token 吊销黑名单、登出、一次性登录 code、代理口径。"""

import datetime
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.platform.identity.models import User
from tests.platform.identity.conftest import create_identity_user

settings = get_settings()


def _make_jwt(user: User, *, jti: str | None = None, expire_s: int = 3600) -> str:
    """按 service._generate_jwt 的口径手工签发 token（绕过飞书流程）。"""
    payload: dict[str, object] = {
        "sub": str(user.id),
        "open_id": user.feishu_open_id,
        "iat": datetime.datetime.now(tz=datetime.UTC),
        "exp": datetime.datetime.now(tz=datetime.UTC)
        + datetime.timedelta(seconds=expire_s),
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


# ── 黑名单 ──────────────────────────────────────────────────────────


async def test_revoked_jti_rejected(
    auth_client: tuple[AsyncClient, AsyncSession],
    _fake_blacklist: dict[str, str],
) -> None:
    """已吊销 jti 的 token 视为未登录（401）。"""
    client, session = auth_client
    user = await create_identity_user(session)
    jti = str(uuid.uuid4())
    _fake_blacklist[f"jwt_blacklist:{jti}"] = "1"
    token = _make_jwt(user, jti=jti)

    # 对照：同一用户、未吊销 jti 的另一个 token 可通过
    resp = await client.get(
        "/api/v1/identity/me",
        headers={"Authorization": f"Bearer {_make_jwt(user, jti=str(uuid.uuid4()))}"},
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_valid_jti_accepted(
    auth_client: tuple[AsyncClient, AsyncSession],
) -> None:
    """未吊销 jti 的 token 正常通过。"""
    client, session = auth_client
    user = await create_identity_user(session)
    token = _make_jwt(user, jti=str(uuid.uuid4()))

    resp = await client.get(
        "/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == user.name


async def test_legacy_token_without_jti_skips_blacklist(
    auth_client: tuple[AsyncClient, AsyncSession],
) -> None:
    """无 jti 的历史 token 跳过黑名单检查（部署过渡期兼容）。"""
    client, session = auth_client
    user = await create_identity_user(session)
    token = _make_jwt(user)  # 不带 jti

    resp = await client.get(
        "/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ── 登出 ────────────────────────────────────────────────────────────


async def test_logout_revokes_token(
    auth_client: tuple[AsyncClient, AsyncSession],
    _fake_blacklist: dict[str, str],
) -> None:
    """登出后原 token 立即失效。"""
    client, session = auth_client
    user = await create_identity_user(session)
    token = _make_jwt(user, jti=str(uuid.uuid4()))

    resp = await client.post(
        "/api/v1/identity/auth/logout", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/api/v1/identity/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_logout_requires_login(client: AsyncClient) -> None:
    """匿名登出 → 401。"""
    resp = await client.post("/api/v1/identity/auth/logout")
    assert resp.status_code == 401


# ── 一次性登录 code ─────────────────────────────────────────────────


async def test_exchange_code_single_use(
    auth_client: tuple[AsyncClient, AsyncSession],
    _fake_login_codes: dict[str, str],
) -> None:
    """code 兑换一次后立即失效。"""
    client, _session = auth_client
    from app.platform.identity.login_codes import CODE_PREFIX, issue_login_code

    await issue_login_code("fake-jwt-token")
    code = next(iter(_fake_login_codes)).removeprefix(f"{CODE_PREFIX}:")

    resp = await client.get(f"/api/v1/identity/auth/exchange?code={code}")
    assert resp.status_code == 200
    assert resp.json()["data"]["token"] == "fake-jwt-token"

    # 第二次使用同一 code → 失效
    resp = await client.get(f"/api/v1/identity/auth/exchange?code={code}")
    assert resp.status_code == 400


async def test_exchange_invalid_code(client: AsyncClient) -> None:
    """未知/过期 code → 400。"""
    resp = await client.get("/api/v1/identity/auth/exchange?code=not-exist")
    assert resp.status_code == 400


# ── Impersonation 角色口径 ──────────────────────────────────────────


@pytest.fixture
def patch_user_permissions(monkeypatch: pytest.MonkeyPatch):
    """把权限查询替换为按 user_id 区分的可控映射（绕开角色表）。"""

    perms_by_user: dict[str, set[str]] = {}

    def _install() -> None:
        import app.platform.permission.deps as perm_deps

        async def _fake(user_id: str, _db: AsyncSession) -> set[str]:
            return perms_by_user.get(user_id, set())

        monkeypatch.setattr(perm_deps, "get_user_permissions", _fake)

    _install()
    return perms_by_user


def _make_impersonate_jwt(admin: User, target: User) -> str:
    return jwt.encode(
        {
            "sub": str(target.id),
            "impersonated_by": str(admin.id),
            "jti": str(uuid.uuid4()),
            "iat": datetime.datetime.now(tz=datetime.UTC),
            "exp": datetime.datetime.now(tz=datetime.UTC)
            + datetime.timedelta(seconds=7200),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


async def test_impersonation_with_admin_role(
    auth_client: tuple[AsyncClient, AsyncSession],
    patch_user_permissions: dict[str, set[str]],
) -> None:
    """拥有 permission:role:manage 的管理员可代理普通用户。"""
    client, session = auth_client
    admin = await create_identity_user(session, name="管理员甲")
    target = await create_identity_user(session, name="被代理乙")
    patch_user_permissions[str(admin.id)] = {"permission:role:manage"}

    client.cookies.set("auth_token", _make_jwt(admin, jti=str(uuid.uuid4())))
    client.cookies.set("impersonate_token", _make_impersonate_jwt(admin, target))

    resp = await client.get("/api/v1/identity/me")
    assert resp.status_code == 200
    assert resp.json()["name"] == "被代理乙"


async def test_impersonation_revoked_admin_falls_back(
    auth_client: tuple[AsyncClient, AsyncSession],
    patch_user_permissions: dict[str, set[str]],
) -> None:
    """管理员被撤权后（无 permission:role:manage），既有代理 token 失效，
    回退为真实用户身份（以角色为准，非 env 静态名单）。"""
    client, session = auth_client
    admin = await create_identity_user(session, name="前管理员丙")
    target = await create_identity_user(session, name="目标丁")
    # admin 曾有代理权限、现被撤销（映射里无记录 → 空权限）
    patch_user_permissions.pop(str(admin.id), None)

    client.cookies.set("auth_token", _make_jwt(admin, jti=str(uuid.uuid4())))
    client.cookies.set("impersonate_token", _make_impersonate_jwt(admin, target))

    resp = await client.get("/api/v1/identity/me")
    assert resp.status_code == 200
    assert resp.json()["name"] == "前管理员丙"


# ── 匿名端点已上锁 ──────────────────────────────────────────────────


async def test_personnel_requires_login(client: AsyncClient) -> None:
    """匿名访问人员名单 → 401。"""
    resp = await client.get("/api/v1/identity/personnel")
    assert resp.status_code == 401


async def test_departments_requires_login(client: AsyncClient) -> None:
    """匿名访问部门列表 → 401。"""
    resp = await client.get("/api/v1/identity/departments")
    assert resp.status_code == 401


async def test_sync_requires_admin(
    auth_client: tuple[AsyncClient, AsyncSession],
) -> None:
    """非管理员（仅登录）触发飞书同步 → 403。"""
    client, session = auth_client
    user = await create_identity_user(session)
    token = _make_jwt(user, jti=str(uuid.uuid4()))
    resp = await client.post(
        "/api/v1/identity/sync/departments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
