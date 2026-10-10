from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app  # noqa: A001
from app.platform.identity.models import User  # noqa: F401
from app.modules.safety.app_config.store import store as _safety_app_config_store

settings = get_settings()

# Test engine uses NullPool so each test gets a fresh connection on its own event loop.
_test_engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=pool.NullPool,
)
_test_session_factory = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
def safety_app_config_db_stub(monkeypatch: pytest.MonkeyPatch):
    """安全模块应用配置中心 DB 层 stub 为空（autouse）。

    生效优先级 env > DB 活行 > 代码默认：stub DB 层保证「未显式 setenv 的键」
    在测试里恒走 env/代码默认，不被本地 dev 库（可能已被启动播种写入真实值）
    的行污染——误发事故教训的防御层。需要 DB 层行为的测试自行覆写本 stub。
    """
    monkeypatch.setattr(_safety_app_config_store, "_fetch_rows", lambda: {})
    _safety_app_config_store.invalidate()
    yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide an AsyncSession that rolls back after each test."""
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Provide an AsyncClient with get_db overridden to use a rolled-back session."""
    async with _test_session_factory() as session:
        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            try:
                yield session
            finally:
                pass  # session lifecycle is managed by the outer fixture

        app.dependency_overrides[get_db] = _override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
        await session.rollback()
