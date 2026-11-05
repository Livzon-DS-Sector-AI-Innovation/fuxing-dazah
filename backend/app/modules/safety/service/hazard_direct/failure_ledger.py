"""① 隐患AI识别失败治理账本 —— attempts / 退避 / 死信（Redis，fail-open）。

背景：改造前失败 = 不写字段 + 下一轮原样重试，永久失败记录会无限烧 AI，
也没有人工兜底的收敛点。本模块把「该记录第几次失败、下次哪轮可重试、
是否已进死信」落到 Redis：

- ``safety:hazard:ai:attempts:{record_id}`` → JSON（TTL 7 天）
  ``{attempts, last_round, next_round, category, last_reason, dead, dead_at}``
- ``safety:hazard:ai:dead_letters`` → HASH（field=record_id，value=JSON）
- ``safety:hazard:ai:round_seq`` → INCR 轮次序号（TTL 7 天）

退避语义：第 1/2/3/4 次失败后 next_round = 当前轮 + 1/3/9/9；
第 ``MAX_ATTEMPTS``(5) 次失败进死信，不再自动重试，留人工查询入口
（``list_dead_letters``）。成功处理会清除 attempts 与死信标记。

**Redis 异常一律 fail-open**（与 ``record_lock`` 同语义）：``should_retry``
返回 True、写失败只记日志 —— Redis 抖动退化为改造前的「每轮重试」，
绝不阻塞识别主流程。

Redis 客户端通过 ``RedisLike`` 协议注入（默认 ``app.core.redis.redis_client``），
测试可注入内存假件。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)

# 退避轮数：第 N 次失败后到「当前轮 + BACKOFF_ROUNDS[N-1]」才重试。
# 只有 3 个档位；第 4 次失败沿用最后一档（9），第 5 次失败直接进死信。
BACKOFF_ROUNDS: tuple[int, ...] = (1, 3, 9)
MAX_ATTEMPTS = 5
TTL_SECONDS = 7 * 24 * 3600

KEY_PREFIX = "safety:hazard:ai:attempts"
DEAD_LETTERS_KEY = "safety:hazard:ai:dead_letters"
ROUND_SEQ_KEY = "safety:hazard:ai:round_seq"
# RAG 基础设施失败（retrieval_degraded/no_chunks）告警去重 key（SET NX EX）
INFRA_ALERT_KEY = "safety:hazard:ai:infra_alert_at"


class RedisLike(Protocol):
    """本模块用到的最小 Redis 协议（测试注入内存假件）。"""

    async def get(self, key: str) -> Any: ...

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> Any: ...

    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> Any: ...

    async def hset(self, key: str, field: str, value: str) -> Any: ...

    async def hgetall(self, key: str) -> dict[str, str]: ...

    async def hdel(self, key: str, field: str) -> Any: ...

    async def delete(self, key: str) -> Any: ...


@dataclass(frozen=True)
class FailureState:
    """一条记录一次失败记录后的状态（供调用方判断告警收敛）。"""

    record_id: str
    attempts: int
    next_round: int | None
    category: str
    reason: str
    dead: bool
    dead_at: float | None
    is_new: bool  # 本轮是否为「首次失败」（attempts == 1）


def _get_redis() -> RedisLike:
    """默认 Redis 客户端（延迟 import：避免测试收集期触碰配置）。"""
    from app.core.redis import redis_client

    return cast(RedisLike, redis_client)


def _resolve(redis: RedisLike | None) -> RedisLike:
    return redis if redis is not None else _get_redis()


def attempts_key(record_id: str) -> str:
    """单条记录的失败状态 key。"""
    return f"{KEY_PREFIX}:{record_id}"


def _decode(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("失败账本 JSON 解析失败，按无状态处理: %r", raw)
        return None
    return payload if isinstance(payload, dict) else None


async def next_round_seq(redis: RedisLike | None = None) -> int:
    """取下一轮序号（Redis INCR，TTL 7 天）。

    fail-open：Redis 异常时用当前时间戳兜底（仍单调递增，供同轮比较；
    ``should_retry`` 在异常时也会 fail-open 返回 True，不会误判）。
    """
    client = _resolve(redis)
    try:
        seq = int(await client.incr(ROUND_SEQ_KEY))
        await client.expire(ROUND_SEQ_KEY, TTL_SECONDS)
        return seq
    except Exception:
        logger.warning("失败账本 round_seq 读取失败，使用时间戳兜底", exc_info=True)
        return int(time.time())


async def should_retry(
    record_id: str, round_seq: int, *, redis: RedisLike | None = None
) -> bool:
    """该记录本轮是否应处理（到点重试 / 首次处理 / 未死信）。

    ``attempts`` key 不存在 = 可重试（首次处理，或该记录的状态已整体过期）。
    状态 TTL（attempts key 与死信索引同为 7 天）到期后重新计数属**刻意策略**：
    超过 7 天没有新失败的人记录不应被永久退避，给一次重新尝试的机会。
    """
    client = _resolve(redis)
    try:
        state = _decode(await client.get(attempts_key(record_id)))
    except Exception:
        logger.warning(
            "失败账本读取失败，fail-open 允许重试: record_id=%s", record_id, exc_info=True
        )
        return True
    if state is None:
        return True
    if state.get("dead"):
        return False
    next_round = state.get("next_round")
    if not isinstance(next_round, int):
        return True
    return round_seq >= next_round


async def record_failure(
    record_id: str,
    round_seq: int,
    category: str,
    reason: str,
    *,
    redis: RedisLike | None = None,
) -> FailureState:
    """记录一次失败；达到上限时写入死信索引。

    fail-open：Redis 异常时返回「首次失败」状态（调用方仍会告警，
    退化为改造前行为），绝不向上抛。
    """
    client = _resolve(redis)
    reason = (reason or "")[:200]
    try:
        state = _decode(await client.get(attempts_key(record_id))) or {}
        attempts = int(state.get("attempts") or 0) + 1
        dead = attempts >= MAX_ATTEMPTS
        dead_at = time.time() if dead else None
        backoff = BACKOFF_ROUNDS[min(attempts - 1, len(BACKOFF_ROUNDS) - 1)]
        next_round: int | None = None if dead else round_seq + backoff
        payload = {
            "attempts": attempts,
            "last_round": round_seq,
            "next_round": next_round,
            "category": category,
            "last_reason": reason,
            "dead": dead,
            "dead_at": dead_at,
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        await client.set(attempts_key(record_id), encoded, ex=TTL_SECONDS)
        if dead:
            dead_payload = {"record_id": record_id, **payload}
            await client.hset(
                DEAD_LETTERS_KEY,
                record_id,
                json.dumps(dead_payload, ensure_ascii=False),
            )
            # 死信 hash 与 attempts key 同 TTL（7 天，新增死信时刷新整个 hash）：
            # 避免「attempts 过期但死信永存」→ 死信复活重复告警 / 永久占位。
            await client.expire(DEAD_LETTERS_KEY, TTL_SECONDS)
            logger.error(
                "① 记录进入死信（不再自动重试）: record_id=%s attempts=%d category=%s reason=%s",
                record_id, attempts, category, reason,
            )
        return FailureState(
            record_id=record_id,
            attempts=attempts,
            next_round=next_round,
            category=category,
            reason=reason,
            dead=dead,
            dead_at=dead_at,
            is_new=attempts == 1,
        )
    except Exception:
        logger.warning(
            "失败账本写入失败，fail-open 视为首次失败: record_id=%s", record_id, exc_info=True
        )
        return FailureState(
            record_id=record_id,
            attempts=1,
            next_round=round_seq + BACKOFF_ROUNDS[0],
            category=category,
            reason=reason,
            dead=False,
            dead_at=None,
            is_new=True,
        )


async def record_success(record_id: str, *, redis: RedisLike | None = None) -> None:
    """记录一次成功：清除 attempts 与死信标记（失败只日志）。"""
    client = _resolve(redis)
    try:
        await client.delete(attempts_key(record_id))
        await client.hdel(DEAD_LETTERS_KEY, record_id)
    except Exception:
        logger.warning(
            "失败账本清除失败（不影响主流程）: record_id=%s", record_id, exc_info=True
        )


async def list_dead_letters(
    limit: int = 100, *, redis: RedisLike | None = None
) -> list[dict[str, Any]]:
    """死信清单（人工查询入口 / 每轮日志摘要）。

    返回按 dead_at 倒序的结构化列表：
    ``record_id / attempts / category / reason / last_round / dead_at``。
    Redis 异常时返回空列表（fail-open）。
    """
    client = _resolve(redis)
    try:
        raw_items = await client.hgetall(DEAD_LETTERS_KEY)
    except Exception:
        logger.warning("失败账本死信读取失败，返回空列表", exc_info=True)
        return []

    items: list[dict[str, Any]] = []
    for record_id, raw in raw_items.items():
        payload = _decode(raw)
        if payload is None:
            continue
        if isinstance(record_id, bytes):
            record_id = record_id.decode("utf-8", errors="replace")
        items.append(
            {
                "record_id": payload.get("record_id") or record_id,
                "attempts": payload.get("attempts", 0),
                "category": payload.get("category", "unknown"),
                "reason": payload.get("last_reason", ""),
                "last_round": payload.get("last_round"),
                "dead_at": payload.get("dead_at") or 0,
            }
        )
    items.sort(key=lambda item: float(item.get("dead_at") or 0), reverse=True)
    return items[: max(0, int(limit))]


async def should_emit_infra_alert(
    round_seq: int,
    interval_seconds: int = 1800,
    *,
    redis: RedisLike | None = None,
) -> bool:
    """RAG 基础设施失败告警去重（SET NX EX，默认 30 分钟窗口）。

    retrieval_degraded / no_chunks 属「基础设施不可用」而非记录自身失败：
    不累计 attempts、不进死信；告警也只在窗口内报一次，避免 RAG 降级期间
    每轮刷屏。返回 True = 本轮应发送告警（首次 / 窗口已过，或 Redis
    异常时 fail-open）；False = 窗口内已告警过。
    """
    client = _resolve(redis)
    ttl = max(1, int(interval_seconds))
    try:
        acquired = await client.set(INFRA_ALERT_KEY, str(round_seq), ex=ttl, nx=True)
        return bool(acquired)
    except Exception:
        logger.warning(
            "RAG 基础设施告警去重失败，fail-open 允许告警", exc_info=True
        )
        return True


async def clear(record_id: str, *, redis: RedisLike | None = None) -> None:
    """人工清除某种记录的全部失败状态（含死信）。"""
    await record_success(record_id, redis=redis)
