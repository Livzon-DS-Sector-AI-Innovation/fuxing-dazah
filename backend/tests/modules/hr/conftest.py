"""HR 模块测试 fixtures。

为所有 HR 测试提供：
- 独立测试库（dazah_test，与开发库隔离，避免互相污染）
- 权限 mock（绕过 require_hr_basic 的 403）
- 登录用户 mock（绕过 get_current_user）
- 随机值生成器（避免唯一键冲突）
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User

# ── 独立测试库（dazah_test）：与开发库隔离，避免测试/开发数据互相污染 ──


def _hr_test_db_url() -> str:
    url = get_settings().DATABASE_URL
    return url if url.rstrip("/").endswith("_test") else f"{url}_test"


_hr_test_engine = create_async_engine(_hr_test_db_url(), poolclass=pool.NullPool)
_test_session_factory = async_sessionmaker(
    _hr_test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session", autouse=True)
def _migrate_hr_test_db() -> Iterator[None]:
    """会话开始时把独立测试库迁移到最新 head（与开发库保持同构）。"""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _hr_test_db_url())
    command.upgrade(cfg, "head")
    yield

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
    "hr:position:read", "hr:position:manage",
    "hr:trainer:read", "hr:trainer:manage",
    "hr:settings:manage",
    "hr:onboarding:approve", "hr:onboarding:manage",
    "hr:departure:manage",
    "hr:training:plan", "hr:training:assessment", "hr:training:questionbank",
    "hr:training:exam", "hr:training:document", "hr:training:manage",
    "hr:training:export", "hr:profile:export", "hr:profile:transfer",
    "hr:recruitment:manage",
    "hr:title:read", "hr:title:manage", "hr:title:scores:read", "hr:title:judge",
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

    async def _override_get_hr_scope() -> HrAccessContext:
        # 与 get_effective_data_scope mock 的 "all" 保持一致：测试不限制数据范围
        return HrAccessContext(
            user=test_user,
            data_scope="all",
            department=None,
            employee_number=test_user.employee_no,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_hr_scope] = _override_get_hr_scope
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
