"""safety 域测试共享 fixture。

sealed_client：给「端点内部会 commit」的 API 测试用——外层事务 +
savepoint 加入的 session 覆写 get_db，端点 commit 只释放 savepoint，
teardown 外层 rollback 兜底清场（防测试数据真写进开发库）。
只读端点测试沿用顶层 tests/conftest.py 的 client/db_session 即可。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app


@pytest.fixture
async def sealed_client() -> AsyncIterator[tuple[AsyncClient, AsyncSession]]:
    """(API client, session)：端点 commit 被外层事务吞掉，测试后整体回滚。"""
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            session = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )()

            async def _override() -> AsyncIterator[AsyncSession]:
                yield session

            app.dependency_overrides[get_db] = _override
            transport = ASGITransport(app=app)
            try:
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac, session
            finally:
                app.dependency_overrides.clear()
                await outer.rollback()
                await session.close()
    finally:
        await engine.dispose()
