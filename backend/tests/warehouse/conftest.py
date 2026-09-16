"""warehouse 测试共享夹具：免登录 + 授予全部仓储权限码的客户端。

数据写入说明：client 夹具覆写 get_db 且不提交，路由内创建的数据在
同一会话内可见、拆卸时随会话回滚，不污染数据库。
created_by 存在外键约束，因此 fake 用户取库中真实用户 id。
"""

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.platform.identity.models import User
from app.platform.permission.deps import require_user

WAREHOUSE_PERMS = {
    "warehouse:stock:read",
    "warehouse:material:read",
    "warehouse:material:create",
    "warehouse:material:update",
    "warehouse:material:delete",
    "warehouse:location:read",
    "warehouse:location:create",
    "warehouse:location:update",
    "warehouse:location:delete",
    "warehouse:movement:read",
    "warehouse:movement:create",
    "warehouse:movement:delete",
    "warehouse:stocktake:read",
    "warehouse:stocktake:create",
    "warehouse:stocktake:update",
    "warehouse:stocktake:confirm",
    "warehouse:stocktake:delete",
    "warehouse:system-config:read",
    "warehouse:plans:list",
    "warehouse:plans:create",
    "warehouse:plans:update",
    "warehouse:plans:cancel",
    "warehouse:intelligence:read",
    "warehouse:intelligence:update",
    "warehouse:replenishment:read",
    "warehouse:replenishment:update",
    "warehouse:reports:read",
}


async def _real_user_id() -> str:
    # 用 NullPool 独立引擎查询：应用池化引擎的连接绑定事件循环，
    # 跨测试复用会触发 "Event loop is closed"。
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=pool.NullPool)
    try:
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            user_id = (await session.execute(select(User.id).limit(1))).scalar_one_or_none()
    finally:
        await engine.dispose()
    if user_id is None:
        pytest.skip("identity.users 无任何用户，无法构造带 created_by 的写入用例")
    return str(user_id)


@pytest.fixture
async def auth_client(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """在 client（get_db 覆写）基础上叠加免登录 + 全量仓储权限集。"""
    from app.platform.permission import deps as permission_deps

    user_id = await _real_user_id()

    async def _fake_user() -> object:
        return object.__new__(
            type("FakeUser", (), {"id": user_id, "name": "验收用户"}),
        )

    async def _fake_perms(user_id_arg: str, db: AsyncSession) -> set[str]:
        return WAREHOUSE_PERMS

    app.dependency_overrides[require_user] = _fake_user
    monkeypatch.setattr(permission_deps, "get_user_permissions", _fake_perms)
    yield client
    app.dependency_overrides.pop(require_user, None)
