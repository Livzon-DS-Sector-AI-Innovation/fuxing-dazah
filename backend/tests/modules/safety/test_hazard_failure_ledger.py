"""T06 失败治理账本 —— fake RedisLike 单测（不连真实 Redis）。

覆盖 ticket 06 验收：
- 第 1/2/3 次失败后 next_round 分别 +1/+3/+9；第 5 次失败标 dead；dead 后不再重试；
- 成功 / clear 清除状态；Redis 异常 fail-open；
- 模拟 55 条永久失败：10 轮 AI 调用总数显著低于「每轮 55 次」基线；
  最终全部收敛进死信且不再调用；死信清单结构化可查。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.hazard_direct import failure_ledger

SEVEN_DAYS = 7 * 24 * 3600


class FakeRedis:
    """最小 RedisLike 假件（get/set/incr/expire/hset/hgetall/hdel/delete）。"""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False
        self.calls: list[str] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key: str) -> Any:
        self._check()
        self.calls.append(f"get:{key}")
        return self.store.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> Any:
        self._check()
        self.calls.append(f"set:{key}")
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str) -> int:
        self._check()
        self.calls.append(f"incr:{key}")
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> Any:
        self._check()
        self.calls.append(f"expire:{key}")
        self.ttls[key] = seconds
        return True

    async def hset(self, key: str, field: str, value: str) -> Any:
        self._check()
        self.calls.append(f"hset:{key}:{field}")
        bucket = self.store.setdefault(key, {})
        bucket[field] = value
        return 1

    async def hgetall(self, key: str) -> dict[str, str]:
        self._check()
        self.calls.append(f"hgetall:{key}")
        bucket = self.store.get(key)
        if not isinstance(bucket, dict):
            return {}
        return dict(bucket)

    async def hdel(self, key: str, field: str) -> Any:
        self._check()
        bucket = self.store.get(key)
        if not isinstance(bucket, dict):
            return 0
        return 1 if bucket.pop(field, None) is not None else 0

    async def delete(self, key: str) -> Any:
        self._check()
        self.calls.append(f"delete:{key}")
        return 1 if self.store.pop(key, None) is not None else 0


async def test_next_round_seq_increments_and_keeps_ttl() -> None:
    redis = FakeRedis()

    assert await failure_ledger.next_round_seq(redis=redis) == 1
    assert await failure_ledger.next_round_seq(redis=redis) == 2
    assert redis.ttls[failure_ledger.ROUND_SEQ_KEY] == SEVEN_DAYS


async def test_unknown_record_should_retry_immediately() -> None:
    redis = FakeRedis()
    assert await failure_ledger.should_retry("rec-never-seen", 7, redis=redis) is True


async def test_backoff_1_3_9_after_each_failure() -> None:
    redis = FakeRedis()

    first = await failure_ledger.record_failure(
        "rec-1", 10, "api_error", "超时", redis=redis
    )
    assert (first.attempts, first.next_round, first.dead) == (1, 11, False)
    assert first.is_new is True
    assert await failure_ledger.should_retry("rec-1", 10, redis=redis) is False
    assert await failure_ledger.should_retry("rec-1", 11, redis=redis) is True

    second = await failure_ledger.record_failure(
        "rec-1", 11, "api_error", "超时", redis=redis
    )
    assert (second.attempts, second.next_round, second.dead) == (2, 14, False)
    assert await failure_ledger.should_retry("rec-1", 13, redis=redis) is False
    assert await failure_ledger.should_retry("rec-1", 14, redis=redis) is True

    third = await failure_ledger.record_failure(
        "rec-1", 14, "api_error", "超时", redis=redis
    )
    assert (third.attempts, third.next_round, third.dead) == (3, 23, False)

    # attempts 明细落 TTL 7 天的 JSON key
    assert redis.ttls[failure_ledger.attempts_key("rec-1")] == SEVEN_DAYS


async def test_fifth_failure_marks_dead_and_dead_letter_is_queryable() -> None:
    redis = FakeRedis()
    state = None
    for round_seq in (1, 2, 5, 14, 23):
        state = await failure_ledger.record_failure(
            "rec-dead", round_seq, "placeholder_basis", "命中占位依据", redis=redis
        )

    assert state is not None
    assert state.attempts == failure_ledger.MAX_ATTEMPTS
    assert state.dead is True
    assert state.next_round is None
    assert await failure_ledger.should_retry("rec-dead", 999, redis=redis) is False

    dead_letters = await failure_ledger.list_dead_letters(redis=redis)
    assert len(dead_letters) == 1
    item = dead_letters[0]
    assert item["record_id"] == "rec-dead"
    assert item["attempts"] == failure_ledger.MAX_ATTEMPTS
    assert item["category"] == "placeholder_basis"
    assert "占位" in item["reason"]
    assert item["dead_at"] > 0
    # 死信 hash 与 attempts key 用同一 7 天 TTL（防「attempts 过期但死信永存」）
    assert redis.ttls[failure_ledger.DEAD_LETTERS_KEY] == SEVEN_DAYS
    assert (
        redis.ttls[failure_ledger.attempts_key("rec-dead")] == SEVEN_DAYS
    )


async def test_record_success_clears_attempts_and_dead_letter() -> None:
    redis = FakeRedis()
    for round_seq in (1, 2, 5, 14, 23):
        await failure_ledger.record_failure(
            "rec-recover", round_seq, "api_error", "boom", redis=redis
        )
    assert len(await failure_ledger.list_dead_letters(redis=redis)) == 1

    await failure_ledger.record_success("rec-recover", redis=redis)

    assert await failure_ledger.should_retry("rec-recover", 999, redis=redis) is True
    assert await failure_ledger.list_dead_letters(redis=redis) == []


async def test_clear_resets_attempt_state() -> None:
    redis = FakeRedis()
    await failure_ledger.record_failure("rec-clear", 1, "api_error", "boom", redis=redis)

    await failure_ledger.clear("rec-clear", redis=redis)

    assert await failure_ledger.should_retry("rec-clear", 1, redis=redis) is True
    assert failure_ledger.attempts_key("rec-clear") not in redis.store


async def test_redis_failure_fail_open() -> None:
    redis = FakeRedis()
    redis.fail = True

    round_seq = await failure_ledger.next_round_seq(redis=redis)
    assert round_seq > 0  # 时间戳兜底
    assert await failure_ledger.should_retry("rec-x", round_seq, redis=redis) is True

    state = await failure_ledger.record_failure(
        "rec-x", round_seq, "api_error", "boom", redis=redis
    )
    assert state.attempts == 1
    assert state.dead is False

    assert await failure_ledger.list_dead_letters(redis=redis) == []
    await failure_ledger.record_success("rec-x", redis=redis)
    await failure_ledger.clear("rec-x", redis=redis)


async def test_ten_rounds_traffic_much_below_every_round_baseline() -> None:
    """55 条永久失败跑 10 轮：调用次数按 1/3/9 退避（round 1/2/5 各 55 次）。"""
    redis = FakeRedis()
    record_ids = [f"rec-{i:03d}" for i in range(55)]
    calls = 0
    per_round: list[int] = []

    for round_seq in range(1, 11):
        round_calls = 0
        for record_id in record_ids:
            if not await failure_ledger.should_retry(record_id, round_seq, redis=redis):
                continue
            round_calls += 1
            await failure_ledger.record_failure(
                record_id, round_seq, "api_error", "永久失败", redis=redis
            )
        per_round.append(round_calls)
        calls += round_calls

    # 基线 = 每轮 55 次 × 10 轮 = 550；退避后只在第 1/2/5 轮重试
    assert per_round[:3] == [55, 55, 0]
    assert per_round[0] + per_round[1] + per_round[2] == 110
    assert per_round[4] == 55  # 第 5 轮 = 第 2 次失败后再 +3
    assert calls == 165
    assert calls < 55 * 10


async def test_permanent_failures_converge_to_dead_letters_and_stop_calling() -> None:
    redis = FakeRedis()
    record_ids = [f"rec-{i:03d}" for i in range(55)]
    per_round: list[int] = []
    total_calls = 0

    for round_seq in range(1, 31):
        round_calls = 0
        for record_id in record_ids:
            if not await failure_ledger.should_retry(record_id, round_seq, redis=redis):
                continue
            round_calls += 1
            await failure_ledger.record_failure(
                record_id, round_seq, "api_error", "永久失败", redis=redis
            )
        per_round.append(round_calls)
        total_calls += round_calls

    # 尝试轮次 = 1/2/5/14/23（1+1/3/9/9 退避），每轮 55 次，共 5 次尝试后死信
    assert per_round[0] == 55
    assert per_round[1] == 55
    assert per_round[2] == 0
    assert per_round[4] == 55
    assert per_round[13] == 55  # round 14
    assert per_round[22] == 55  # round 23 = 第 5 次失败 → 死信
    assert total_calls == 55 * 5
    # 死信后不再调用
    assert sum(per_round[23:]) == 0

    dead_letters = await failure_ledger.list_dead_letters(limit=100, redis=redis)
    assert len(dead_letters) == 55
    categories = {item["category"] for item in dead_letters}
    assert categories == {"api_error"}
    assert all(item["attempts"] == failure_ledger.MAX_ATTEMPTS for item in dead_letters)


async def test_list_dead_letters_respects_limit() -> None:
    redis = FakeRedis()
    for i in range(3):
        for round_seq in (1, 2, 5, 14, 23):
            await failure_ledger.record_failure(
                f"rec-{i}", round_seq, "api_error", "boom", redis=redis
            )

    assert len(await failure_ledger.list_dead_letters(limit=2, redis=redis)) == 2
    assert len(await failure_ledger.list_dead_letters(redis=redis)) == 3


def test_round_result_deferred_is_backward_compatible() -> None:
    from app.modules.safety.service.hazard_direct.round_result import RoundResult

    result = RoundResult(job_label="隐患AI分析轮询")
    assert result.deferred == 0
    payload = result.as_dict()
    assert payload["deferred"] == 0
    # 旧字段保持
    for key in ("job_label", "total", "succeeded", "failed", "failures"):
        assert key in payload, key

    result.deferred = 3
    assert result.as_dict()["deferred"] == 3



async def test_should_emit_infra_alert_dedups_within_window() -> None:
    redis = FakeRedis()

    assert (
        await failure_ledger.should_emit_infra_alert(11, redis=redis)
    ) is True
    # 同一窗口内第二次 → 不再告警（SET NX 未获得）
    assert (
        await failure_ledger.should_emit_infra_alert(12, redis=redis)
    ) is False
    assert redis.ttls[failure_ledger.INFRA_ALERT_KEY] == 1800


async def test_should_emit_infra_alert_custom_interval() -> None:
    redis = FakeRedis()

    assert (
        await failure_ledger.should_emit_infra_alert(
            1, interval_seconds=60, redis=redis
        )
    ) is True
    assert redis.ttls[failure_ledger.INFRA_ALERT_KEY] == 60


async def test_should_emit_infra_alert_fail_open() -> None:
    redis = FakeRedis()
    redis.fail = True

    assert (
        await failure_ledger.should_emit_infra_alert(1, redis=redis)
    ) is True
