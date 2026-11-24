"""权限模块测试夹具：将 Redis 权限缓存替换为 no-op，测试不依赖 Redis。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import Department, User
from app.platform.permission.models import Permission, Role

ApiFactory = Callable[[User, set[str]], AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture(autouse=True)
def _no_redis_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """将权限缓存读写全部替换为 no-op，保证测试可离线运行。"""
    import app.platform.permission.cache as cache_mod
    import app.platform.permission.deps as deps_mod

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    async def _none(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cache_mod, "cache_get", _none)
    monkeypatch.setattr(cache_mod, "cache_set", _noop)
    monkeypatch.setattr(cache_mod, "cache_delete", _noop)
    monkeypatch.setattr(cache_mod, "invalidate_user_cache", _noop)
    monkeypatch.setattr(cache_mod, "invalidate_all_caches", _noop)
    # deps.get_user_permissions 直接 import 了 cache 函数，需同步替换
    monkeypatch.setattr(deps_mod, "get_cached_permissions", _none)
    monkeypatch.setattr(deps_mod, "set_cached_permissions", _noop)


@pytest.fixture
async def make_permission(db_session: AsyncSession):
    """创建权限记录的工厂，code 缺省时生成唯一编码避免与库中已有权限冲突。"""

    async def _make(
        code: str | None = None, module: str = "equipment",
    ) -> Permission:
        code = code or f"{module}:res:{uuid.uuid4().hex[:8]}"
        perm = Permission(
            code=code,
            name=f"权限{code}",
            module=module,
            resource=code.split(":")[1],
            action=code.split(":")[2],
        )
        db_session.add(perm)
        await db_session.flush()
        return perm

    return _make


@pytest.fixture
async def make_role(db_session: AsyncSession):
    """创建角色的工厂。"""

    async def _make(
        code: str | None = None,
        data_scope: str = "department",
        is_system: bool = False,
        group_feishu_department_id: str | None = None,
    ) -> Role:
        role = Role(
            code=code or f"role_{uuid.uuid4().hex[:8]}",
            name="测试角色",
            data_scope=data_scope,
            is_system=is_system,
            group_feishu_department_id=group_feishu_department_id,
        )
        db_session.add(role)
        await db_session.flush()
        return role

    return _make


@pytest.fixture
async def make_user(db_session: AsyncSession):
    """创建用户的工厂，feishu_department_ids 为 JSON 数组字符串。"""

    async def _make(
        dept_ids: list[str] | None = None,
        name: str | None = None,
    ) -> User:
        user = User(
            name=name or f"用户{uuid.uuid4().hex[:6]}",
            employee_no=f"EMP-{uuid.uuid4().hex[:8].upper()}",
            feishu_department_ids=(
                json.dumps(dept_ids) if dept_ids is not None else None
            ),
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make


@pytest.fixture
async def make_department(db_session: AsyncSession):
    """创建部门的工厂。"""

    async def _make(
        dept_id: str, parent_id: str | None = None, name: str | None = None,
    ) -> Department:
        dept = Department(
            feishu_department_id=dept_id,
            name=name or f"部门{dept_id}",
            parent_feishu_department_id=parent_id,
        )
        db_session.add(dept)
        await db_session.flush()
        return dept

    return _make


@pytest.fixture
async def api(db_session: AsyncSession) -> ApiFactory:
    """以「指定用户 + 指定权限集合」换取 API client；与 db_session 同事务，工厂造的数据端点可见。

    注意：该夹具只 patch 端点门禁用的 `deps.get_user_permissions`；
    service 层的范围守卫直接读数据库，相关用例需给操作者真实授予角色/权限。
    """

    @asynccontextmanager
    async def _client(
        user: User, perms: set[str],
    ) -> AsyncGenerator[AsyncClient, None]:
        async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
            yield db_session

        async def _override_user() -> User:
            return user

        async def _perms(user_id: str, db: object) -> set[str]:
            return set(perms)

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = _override_user
        try:
            with patch(
                "app.platform.permission.deps.get_user_permissions", new=_perms
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac
        finally:
            app.dependency_overrides.clear()

    return _client
