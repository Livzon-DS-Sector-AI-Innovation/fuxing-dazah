"""Equipment module test fixtures."""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.modules.equipment.deps import EquipmentAccessContext
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


@pytest.fixture(autouse=True)
def _mock_notifications() -> Iterator[AsyncMock]:
    """Mock 飞书通知，避免任何 equipment 测试触发外部调用。

    autouse，整个 equipment 目录生效。yield send_work_order_notification 的
    mock，供需要断言"是否通知了执行人"的测试直接请求本 fixture 取用。
    patch 源模块属性，因业务代码是运行时 from ... import，故能拦截。
    """
    with (
        patch(
            "app.modules.equipment.service.inspection_notification."
            "send_inspection_start_notification",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.equipment.service.inspection_notification."
            "send_work_order_notification",
            new_callable=AsyncMock,
        ) as wo_notify,
    ):
        yield wo_notify


@pytest.fixture
def make_access_ctx() -> Callable[[User], EquipmentAccessContext]:
    """构造无数据范围限制的 EquipmentAccessContext（data_scope="all"）。

    工单/巡检 service 已统一改为接收 ctx（而非裸 user_id），测试用本工厂
    把某个 User 包成可通过所有权校验的 ctx。
    """

    def _make(user: User) -> EquipmentAccessContext:
        return EquipmentAccessContext(user=user, data_scope="all")

    return _make


# 全部 equipment 权限码，用于在 API 测试中绕过 require_permission 的 403。
_ALL_PERMS: set[str] = {
    "equipment:asset:create",
    "equipment:asset:delete",
    "equipment:asset:import",
    "equipment:asset:read",
    "equipment:asset:update",
    "equipment:inspection:create",
    "equipment:inspection:delete",
    "equipment:inspection:read",
    "equipment:inspection:update",
    "equipment:maintenance:create",
    "equipment:maintenance:delete",
    "equipment:maintenance:read",
    "equipment:maintenance:update",
    "equipment:personnel:manage",
    "equipment:personnel:read",
    "equipment:spare_part:create",
    "equipment:spare_part:delete",
    "equipment:spare_part:read",
    "equipment:spare_part:update",
    "equipment:stats:read",
    "equipment:work_order:approve",
    "equipment:work_order:create",
    "equipment:work_order:read",
    "equipment:work_order:update",
}


@pytest.fixture(autouse=True)
def _grant_permissions() -> Iterator[None]:
    """给测试用户放行全部 equipment 权限并设为全量数据范围。

    autouse，整个 equipment 目录生效。对不走 client 的 service/repo 测试是无害
    的空 patch；对 API 测试则绕过 require_equipment_access 的 403。
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


def _uid() -> str:
    """生成 6 位大写十六进制随机后缀，避免共享测试库的唯一键冲突。"""
    return uuid.uuid4().hex[:6].upper()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide an AsyncSession that rolls back after each test."""
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def _equipment_session() -> AsyncIterator[AsyncSession]:
    """Shared session for equipment API tests with test users pre-created."""
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def test_reporter(_equipment_session: AsyncSession) -> User:
    """Create a test reporter user in the shared session."""
    user = User(name="测试报修人", employee_no=f"EMP-R-{uuid.uuid4().hex[:8]}")
    _equipment_session.add(user)
    await _equipment_session.flush()
    await _equipment_session.refresh(user)
    return user


@pytest.fixture
async def test_assignee(_equipment_session: AsyncSession) -> User:
    """Create a test assignee user in the shared session."""
    user = User(name="测试维修员", employee_no=f"EMP-A-{uuid.uuid4().hex[:8]}")
    _equipment_session.add(user)
    await _equipment_session.flush()
    await _equipment_session.refresh(user)
    return user


@pytest.fixture
async def client(
    _equipment_session: AsyncSession,
    test_reporter: User,
) -> AsyncIterator[AsyncClient]:
    """Provide an AsyncClient with get_db and get_current_user overridden."""
    session = _equipment_session

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        try:
            yield session
        finally:
            pass

    async def _override_get_current_user() -> User:
        return test_reporter

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
