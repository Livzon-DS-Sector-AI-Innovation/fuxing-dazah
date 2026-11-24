from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app  # noqa: A001
from app.platform.identity.models import User  # noqa: F401

settings = get_settings()

# 安全模块已独立成单独项目，本仓库停用其功能；测试文件保留为静态存档不再收集
collect_ignore_glob = ["modules/safety/*"]

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
