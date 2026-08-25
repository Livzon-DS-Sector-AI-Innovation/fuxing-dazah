"""工具箱测试共享设施。"""

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
import redis.asyncio as redis


class FakeRedis:
    """最小 redis.asyncio.Redis 替身：get/set/expire。"""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        self.store[key] = value.encode() if isinstance(value, str) else value
        if ex:
            self.ttls[key] = ex

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


@pytest.fixture
def fake_redis() -> redis.Redis:
    return cast(redis.Redis, FakeRedis())


@pytest.fixture
def fake_user() -> SimpleNamespace:
    """假用户：合法 UUID 字符串 id（工具箱权限判定会解析为 UUID）。"""
    return SimpleNamespace(id=str(uuid.uuid4()))


@pytest.fixture(autouse=True)
def _no_platform_permission_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """权限判定离线：将平台权限查询替换为固定返回（默认无任何权限）。

    toolbox 权限判定的超管分支依赖平台 get_user_permissions（走 Redis 缓存），
    测试中替换掉以避免依赖 Redis；需要超管放行的用例可再次 monkeypatch。
    """
    import app.modules.toolbox.service as service_mod

    async def _no_perms(_user_id: str, _db: object) -> set[str]:
        return set()

    monkeypatch.setattr(service_mod, "get_user_permissions", _no_perms)
