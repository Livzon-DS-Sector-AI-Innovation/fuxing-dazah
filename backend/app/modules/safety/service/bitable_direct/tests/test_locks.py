"""底座 per-record 锁 单测（假 Redis，无网络）。

覆盖票据 05 验收项：获取 / 释放、抢不到时明确失败、Redis 不可用时降级不阻塞、
异常路径仍释放锁、key 与 hazard 既有实现逐字一致。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct import locks


class FakeRedis:
    """替身 Redis：只实现 SET NX EX 与 DELETE。"""

    def __init__(
        self,
        *,
        acquired: bool = True,
        set_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.acquired = acquired
        self.set_error = set_error
        self.delete_error = delete_error
        self.set_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> Any:
        if self.set_error is not None:
            raise self.set_error
        self.set_calls.append({"key": key, "value": value, "ex": ex, "nx": nx})
        return "OK" if self.acquired else None

    async def delete(self, key: str) -> Any:
        if self.delete_error is not None:
            raise self.delete_error
        self.delete_calls.append(key)
        return 1


class TestRecordLockKey:
    def test_matches_hazard_key(self) -> None:
        assert (
            locks.record_lock_key("hazard", "rec1")
            == "safety:hazard:direct:lock:rec1"
        )

    def test_domain_is_lowercased(self) -> None:
        assert locks.record_lock_key("HAZARD", "rec1") == (
            "safety:hazard:direct:lock:rec1"
        )
        assert locks.record_lock_key("Special_Op", "rec2") == (
            "safety:special_op:direct:lock:rec2"
        )


class TestRecordLock:
    async def test_acquired_then_released(self) -> None:
        redis = FakeRedis(acquired=True)
        key = "safety:hazard:direct:lock:rec1"

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=600, redis=redis
        ) as acquired:
            assert acquired is True

        assert redis.set_calls == [
            {"key": key, "value": "1", "ex": 600, "nx": True}
        ]
        assert redis.delete_calls == [key]

    async def test_contended_is_false_and_not_released(self) -> None:
        redis = FakeRedis(acquired=False)

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=600, redis=redis
        ) as acquired:
            assert acquired is False

        assert len(redis.set_calls) == 1
        assert redis.delete_calls == []

    async def test_redis_down_degrades_to_acquired(self) -> None:
        """SET 与 DELETE 全挂：降级为不阻塞，且释放失败被吞掉，不抛异常。"""
        redis = FakeRedis(
            set_error=ConnectionError("redis down"),
            delete_error=ConnectionError("redis down"),
        )

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=600, redis=redis
        ) as acquired:
            assert acquired is True

        assert redis.set_calls == []
        assert redis.delete_calls == []

    async def test_set_failure_still_attempts_release(self) -> None:
        """与 hazard 既有实现同形：SET 抛错后仍试一次 DELETE（失败只记日志）。"""
        redis = FakeRedis(set_error=ConnectionError("redis down"))
        key = "safety:hazard:direct:lock:rec1"

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=600, redis=redis
        ) as acquired:
            assert acquired is True

        assert redis.set_calls == []
        assert redis.delete_calls == [key]

    async def test_release_failure_does_not_raise(self) -> None:
        redis = FakeRedis(delete_error=ConnectionError("redis down"))

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=600, redis=redis
        ) as acquired:
            assert acquired is True

    async def test_body_exception_still_releases(self) -> None:
        redis = FakeRedis(acquired=True)
        key = "safety:hazard:direct:lock:rec1"

        with pytest.raises(RuntimeError, match="boom"):
            async with locks.record_lock(
                "rec1", domain="hazard", ttl_seconds=60, redis=redis
            ):
                raise RuntimeError("boom")

        assert redis.delete_calls == [key]

    async def test_ttl_forwarded(self) -> None:
        redis = FakeRedis(acquired=True)

        async with locks.record_lock(
            "rec1", domain="hazard", ttl_seconds=123, redis=redis
        ):
            pass

        assert redis.set_calls[0]["ex"] == 123
