"""Energy module test fixtures."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.modules.energy.models import EnergyTypeConfig
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User

settings = get_settings()

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
def sample_device_config_data() -> dict[str, object]:
    return {
        "platform_code": "zhiheng",
        "platform_device_code": "WD-001",
        "device_name": "1号水表",
        "energy_type": "water",
        "api_endpoint": "/api/v1/water/hourly",
        "workshop": "发酵车间",
        "production_line": "发酵产线A",
        "monitor_level": "normal",
        "unit": "m3",
        "is_enabled": True,
    }


async def _ensure_water_type_config(session: AsyncSession) -> EnergyTypeConfig:
    """确保 water 能源类型配置存在（service 创建设备需据此查 unit）。"""
    existing = await session.scalar(
        select(EnergyTypeConfig).where(
            EnergyTypeConfig.type_code == "water",
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
    )
    if existing is not None:
        return existing
    config = EnergyTypeConfig(
        type_code="water",
        display_name="水",
        unit="m3",
        sort_order=1,
        collect_granularity="hourly",
    )
    session.add(config)
    await session.flush()
    return config


@pytest.fixture
async def water_energy_type_config(db_session: AsyncSession) -> EnergyTypeConfig:
    """供 service 层测试使用：确保 water 能源类型配置存在。"""
    return await _ensure_water_type_config(db_session)


# 全部 energy 权限码，用于在 API 测试中绕过 require_permission 的 401/403。
_ALL_PERMS: set[str] = {
    "energy:device:create",
    "energy:device:delete",
    "energy:device:read",
    "energy:device:update",
    "energy:overview:delete",
    "energy:overview:read",
    "energy:collect:trigger",
    "energy:collect_log:delete",
    "energy:collect_log:read",
    "energy:alert:create",
    "energy:alert:delete",
    "energy:alert:read",
    "energy:alert:update",
    "energy:alert:process:approve",
    "energy:alert:process:reject",
    "energy:type_config:create",
    "energy:type_config:delete",
    "energy:type_config:read",
    "energy:type_config:update",
    "energy:workshop_config:create",
    "energy:workshop_config:delete",
    "energy:workshop_config:read",
    "energy:workshop_config:update",
    "energy:daily_report:create",
    "energy:daily_report:delete",
    "energy:daily_report:read",
    "energy:daily_report:send",
    "energy:daily_report:update",
    "energy:nitrogen_report:create",
    "energy:nitrogen_report:delete",
    "energy:nitrogen_report:read",
    "energy:nitrogen_report:send",
    "energy:nitrogen_report:update",
}


@pytest.fixture(autouse=True)
def _grant_permissions() -> Iterator[None]:
    """放行全部 energy 权限并设为全量数据范围，绕过 API 测试的鉴权。

    autouse，整个 energy 目录生效。对不走 client 的 service/repo 测试是无害
    的空 patch；对 API 测试则绕过 require_permission 的 401/403。
    """

    async def _all_perms(user_id: str, db: object) -> set[str]:
        return _ALL_PERMS

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


@pytest.fixture(autouse=True)
def _isolate_scheduler_session() -> Iterator[None]:
    """scheduler 内部用生产 async_session_factory（QueuePool）开会话。

    生产引擎的连接池会跨测试 event loop 复用连接，导致 asyncpg 报
    「connection terminating」并让 trigger_collection 误判为 failed。
    此处替换为 NullPool 测试工厂，每次调用都拿新连接，避免跨 loop 污染。
    """
    with patch(
        "app.modules.energy.scheduler.async_session_factory",
        new=_test_session_factory,
    ):
        yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """energy API 测试 client：覆盖 get_db、get_current_user，并预置 water 类型配置。"""
    async with _test_session_factory() as session:
        user = User(name="测试用户", employee_no=f"EMP-E-{uuid.uuid4().hex[:8]}")
        session.add(user)
        await session.flush()

        await _ensure_water_type_config(session)

        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            yield session

        async def _override_get_current_user() -> User:
            return user

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = _override_get_current_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
        await session.rollback()
