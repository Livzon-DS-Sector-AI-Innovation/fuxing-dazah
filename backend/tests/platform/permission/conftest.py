"""权限模块测试夹具：将 Redis 权限缓存替换为 no-op，测试不依赖 Redis。"""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import Department, User
from app.platform.permission.models import Permission, Role


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
    ) -> Role:
        role = Role(
            code=code or f"role_{uuid.uuid4().hex[:8]}",
            name="测试角色",
            data_scope=data_scope,
            is_system=is_system,
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
