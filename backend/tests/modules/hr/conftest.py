"""HR 模块测试 fixtures。

为所有 HR 测试提供：
- 权限 mock（绕过 require_hr_basic 的 403）
- 登录用户 mock（绕过 get_current_user）
- 随机值生成器（避免共享数据库唯一键冲突）
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory  # noqa: F401 — 复用根 conftest 的 session factory


# ── 全部 HR 权限码（测试用超管视角） ──
_ALL_HR_PERMS: set[str] = {
    "hr:department:read", "hr:department:create", "hr:department:update", "hr:department:delete",
    "hr:profile:read", "hr:profile:create", "hr:profile:update", "hr:profile:delete",
    "hr:recruitment:read", "hr:recruitment:create", "hr:recruitment:update", "hr:recruitment:delete",
    "hr:onboarding:read", "hr:onboarding:create", "hr:onboarding:update", "hr:onboarding:delete",
    "hr:departure:read", "hr:departure:create", "hr:departure:update", "hr:departure:delete",
    "hr:training:read", "hr:training:create", "hr:training:update", "hr:training:delete",
    "hr:dashboard:read", "hr:roster:read",
    "hr:employee:read", "hr:employee:create", "hr:employee:update", "hr:employee:delete",
    "hr:employee:export", "hr:employee:transfer",
    "hr:org:read", "hr:org:manage",
    "hr:settings:manage",
    "hr:onboarding:approve", "hr:onboarding:manage",
    "hr:departure:manage",
    "hr:training:plan", "hr:training:assessment", "hr:training:questionbank",
    "hr:training:exam", "hr:training:document", "hr:training:manage",
    "hr:recruitment:manage",
}


# ── 辅助函数 ──

def _rand(prefix: str = "") -> str:
    """生成带随机后缀的唯一值，避免共享测试库唯一键冲突。"""
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{suffix}" if prefix else suffix


# ── 权限 mock（autouse，整个 HR 测试目录生效） ──

@pytest.fixture(autouse=True)
def _grant_hr_permissions() -> Iterator[None]:
    """给测试用户放行全部 HR 权限 + 全量数据范围。

    autouse，所有 HR 测试自动绕过权限检查。
    """
    async def _all_perms(user_id: str, db: object) -> set[str]:
        return _ALL_HR_PERMS

    with (
        patch(
            "app.platform.permission.deps.get_user_permissions",
            new=_all_perms,
        ),
        patch(
            "app.platform.permission.repository.PermissionRepository"
            ".get_effective_data_scope",
            new_callable=AsyncMock,
            return_value="all",
        ),
    ):
        yield


# ── 数据库 session（复用根 conftest 的 NullPool engine） ──

@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """提供回滚式 AsyncSession，每个测试结束后自动回滚。"""
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


# ── 测试用户（API 测试用） ──

@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """在测试 DB 中创建一个临时用户，用于 API 鉴权。"""
    user = User(
        name="HR测试员",
        employee_no=f"HR-TEST-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


# ── API client（覆盖 DB session + 登录用户） ──

@pytest.fixture
async def client(db_session: AsyncSession, test_user: User) -> AsyncIterator[AsyncClient]:
    """HTTP 测试客户端，绕过真实鉴权直接以 test_user 身份调用 API。"""
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        finally:
            pass

    async def _override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
