"""工具箱测试共享设施。"""

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
    return SimpleNamespace(id="user-1")
