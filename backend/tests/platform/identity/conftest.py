"""身份认证测试夹具：内存版黑名单 / 登录 code，测试不依赖 Redis。"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.platform.identity.models import User

_settings = get_settings()
_engine = create_async_engine(_settings.DATABASE_URL, poolclass=pool.NullPool)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _fake_blacklist(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """token_blacklist 的 Redis 读写替换为内存 dict（键即 jti 黑名单）。"""
    import app.platform.identity.token_blacklist as bl

    store: dict[str, str] = {}

    async def fake_get(key: str) -> str | None:
        return store.get(key)

    async def fake_set(key: str, value: str, ex: int = 3600) -> None:
        store[key] = value

    monkeypatch.setattr(bl, "cache_get", fake_get)
    monkeypatch.setattr(bl, "cache_set", fake_set)
    return store


@pytest.fixture(autouse=True)
def _fake_login_codes(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """login_codes 的 Redis 客户端替换为内存版（一次性 code 存取）。"""
    import app.platform.identity.login_codes as lc

    codes: dict[str, str] = {}

    class _FakeRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            codes[key] = value

        async def getdel(self, key: str) -> str | None:
            return codes.pop(key, None)

    async def fake_get_redis() -> _FakeRedis:
        return _FakeRedis()

    monkeypatch.setattr(lc, "get_redis", fake_get_redis)
    return codes


@pytest.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, AsyncSession]]:
    """client + 与 app 共用同一事务的 session（造的用户对接口可见，结束回滚）。"""
    async with _session_factory() as session:
        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db] = _override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, session
        app.dependency_overrides.clear()
        await session.rollback()


async def create_identity_user(session: AsyncSession, name: str | None = None) -> User:
    """创建带 feishu_open_id 的用户（get_current_user 按 open_id 查库）。"""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        name=name or f"测试用户{suffix[:4]}",
        employee_no=f"EMP-{suffix.upper()}",
        feishu_open_id=f"ou_test_{suffix}",
        feishu_user_id=f"ui_test_{suffix}",
    )
    session.add(user)
    await session.flush()
    return user
