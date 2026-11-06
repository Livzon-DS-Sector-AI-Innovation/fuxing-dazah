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
from datetime import UTC, datetime
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
# RAG 基础设施失败（retrieval_degraded）告警去重 key（SET NX EX）
INFRA_ALERT_KEY = "safety:hazard:ai:infra_alert_at"
# AI 基础设施失败（欠费/鉴权/服务端/超时/连接/配置）告警独立去重 key：
# 与 RAG infra 互不吞并，两路故障可各自告警一次（F1-3）。
AI_INFRA_ALERT_KEY = "safety:hazard:ai:ai_infra_alert_at"
# RAG 全局降级短路熔断（C5/F9）告警独立去重 key：与上面两路互不吞并。
RAG_BREAKER_ALERT_KEY = "safety:hazard:ai:rag_breaker_alert_at"

# 进程内轮次序号（B7-1 / F6）：Redis 故障期间本地自增，恢复后仍不回退。
_LAST_SEQ = 0


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

    async def hget(self, key: str, field: str) -> Any: ...

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
    """取下一轮序号（Redis INCR，TTL 7 天；进程内单调不回退）。

    B7-1 / F6：模块级 ``_LAST_SEQ`` 保证**进程内单调**——Redis 异常时本地
    ``+1`` 兜底（不再像旧实现返回时间戳），Redis 恢复后返回值也不低于故障
    期间已发序号。退避判定依赖 ``round_seq >= next_round``，序号回退会导致
    记录被误判永远「未到重试轮次」，故必须单调。
    """
    global _LAST_SEQ
    try:
        client = _resolve(redis)
        seq = int(await client.incr(ROUND_SEQ_KEY))
        await client.expire(ROUND_SEQ_KEY, TTL_SECONDS)
        # 成功 INCR 后仍取进程内最大值：Redis 计数被重置/落后时也不回退到
        # 故障期间已发序号之下（返回同一序号是非降，不影响退避比较语义）。
        _LAST_SEQ = max(_LAST_SEQ, seq)
        return _LAST_SEQ
    except Exception:
        _LAST_SEQ += 1
        logger.warning(
            "失败账本 round_seq 读取失败，使用进程内单调序号兜底: seq=%d",
            _LAST_SEQ,
            exc_info=True,
        )
        return _LAST_SEQ


async def retry_status(
    record_id: str, round_seq: int, *, redis: RedisLike | None = None
) -> str:
    """该记录本轮可执行状态：``"ok"`` / ``"backoff"`` / ``"dead"``。

    - attempts key 存在：``dead`` → ``"dead"``；未到 ``next_round`` → ``"backoff"``；
      到点/无退避字段 → ``"ok"``；
    - attempts key 缺失（首次处理 / 7 天 TTL 到期 / 人工清除）→ **补查死信
      hash**：命中 → ``"dead"``，否则 ``"ok"``（F5：防「attempts 过期但死信
      hash 因后续新增死信刷新而仍存在」时死信复活重复烧 AI）；
    - Redis 异常 fail-open ``"ok"``（绝不阻塞识别主流程）。
    """
    client = _resolve(redis)
    try:
        state = _decode(await client.get(attempts_key(record_id)))
        if state is not None:
            if state.get("dead"):
                return "dead"
            next_round = state.get("next_round")
            if not isinstance(next_round, int):
                return "ok"
            return "ok" if round_seq >= next_round else "backoff"
        # F5：attempts 状态缺失时补查死信 hash（跨 TTL 死信 fail-safe）
        dead_marker = await client.hget(DEAD_LETTERS_KEY, record_id)
        return "dead" if dead_marker else "ok"
    except Exception:
        logger.warning(
            "失败账本读取失败，fail-open 视为可重试: record_id=%s",
            record_id,
            exc_info=True,
        )
        return "ok"


async def should_retry(
    record_id: str, round_seq: int, *, redis: RedisLike | None = None
) -> bool:
    """该记录本轮是否应处理（到点重试 / 首次处理 / 未死信）。

    行为委托 :func:`retry_status`（``"ok"`` 才处理），含 F5 跨 TTL 死信
    fail-safe；Redis 异常时 fail-open 返回 True。

    attempts key 与死信 hash 均过期（7 天无任何新失败）后重新计数属**刻意
    策略**：长期无失败的人记录给一次重新尝试的机会。
    """
    return (await retry_status(record_id, round_seq, redis=redis)) == "ok"


async def record_failure(
    record_id: str,
    round_seq: int,
    category: str,
    reason: str,
    *,
    redis: RedisLike | None = None,
) -> FailureState:
    """记录一次失败；达到上限时写入死信索引。

    写入顺序（B7-1 / F6）：**死信 hash（若本轮 dead）→ attempts payload →
    死信 hash EXPIRE**。先写死信再写 attempts，保证不会出现「attempts 标
    dead 但死信 hash 缺失」的静默丢死信：死信 hash 写失败时立即退出，
    attempts 保持上一轮状态（不标 dead）。

    fail-open：``_resolve``/参数解析/各写入步骤异常一律不向上抛，返回
    ``is_new=False`` 的兜底状态（避免基础设施抖动被放大成「新增失败」告警
    风暴），只记 warning 日志。
    """
    reason = (reason or "")[:200]
    try:
        client = _resolve(redis)
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
        if dead:
            # 先写死信 hash：写失败则本次不写 attempts（不标 dead），
            # 死信索引与 attempts 状态不会出现「标死但索引缺失」。
            dead_payload = {"record_id": record_id, **payload}
            await client.hset(
                DEAD_LETTERS_KEY,
                record_id,
                json.dumps(dead_payload, ensure_ascii=False),
            )
        encoded = json.dumps(payload, ensure_ascii=False)
        await client.set(attempts_key(record_id), encoded, ex=TTL_SECONDS)
        if dead:
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
        # 写入非原子：极端半写（HSET 死信成功、SET attempts 失败）会出现
        # 「死信 hash 可见但 attempts 未标 dead」，下轮失败会重写 attempts ——
        # 属可接受的失败安全侧（不会静默停摆，也不产生告警风暴）。
        logger.warning(
            "失败账本写入失败，fail-open 返回非新增失败状态: record_id=%s",
            record_id,
            exc_info=True,
        )
        return FailureState(
            record_id=record_id,
            attempts=1,
            next_round=round_seq + BACKOFF_ROUNDS[0],
            category=category,
            reason=reason,
            dead=False,
            dead_at=None,
            is_new=False,  # 不进入「本轮新增失败」告警集合，避免告警风暴
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


def format_dead_letter_lines(
    items: list[dict[str, Any]], limit: int = 10, *, max_reason: int = 60
) -> list[str]:
    """死信 top-N 明细行（①轮末日志 / 只读查询脚本共用的摘要格式）。

    每条：``record_id [category] 第 attempts 次 · dead_at · last_reason 摘要``。
    ``items`` 采用 :func:`list_dead_letters` 的输出结构（已按 dead_at 倒序）；
    ``limit`` 只控制展示条数（top-N），不改变数据。
    """
    lines: list[str] = []
    for item in items[: max(0, int(limit))]:
        reason = str(item.get("reason") or "")
        if len(reason) > max_reason:
            reason = reason[: max_reason - 1] + "…"
        when = "-"
        dead_at = item.get("dead_at")
        if isinstance(dead_at, (int, float)) and dead_at > 0:
            when = datetime.fromtimestamp(float(dead_at), tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(
            f"{item.get('record_id', '')} [{item.get('category', 'unknown')}] "
            f"第 {item.get('attempts', '?')} 次 · {when} · {reason}"
        )
    return lines


async def should_emit_infra_alert(
    round_seq: int,
    interval_seconds: int = 1800,
    *,
    redis: RedisLike | None = None,
    key: str = INFRA_ALERT_KEY,
) -> bool:
    """基础设施失败告警去重（SET NX EX，默认 30 分钟窗口）。

    ``retrieval_degraded`` / AI 端点基础设施失败属「基础设施不可用」而非记录
    自身失败：不累计 attempts、不进死信；告警也只在窗口内报一次，避免故障
    期间每轮刷屏。``key`` 区分两路告警：RAG 用 ``INFRA_ALERT_KEY``，AI 用
    独立的 ``AI_INFRA_ALERT_KEY``（两路互不吞并）。返回 True = 本轮应发送
    告警（首次 / 窗口已过，或 Redis 异常时 fail-open）；False = 窗口内已告警过。

    注：``no_chunks`` 属数据性零召回（R1-3），已改为记录级（计 attempts/死信），
    不再走本去重告警。
    """
    client = _resolve(redis)
    ttl = max(1, int(interval_seconds))
    try:
        acquired = await client.set(key, str(round_seq), ex=ttl, nx=True)
        return bool(acquired)
    except Exception:
        logger.warning(
            "基础设施告警去重失败，fail-open 允许告警: key=%s", key, exc_info=True
        )
        return True


async def clear(record_id: str, *, redis: RedisLike | None = None) -> None:
    """人工清除某种记录的全部失败状态（含死信）。"""
    await record_success(record_id, redis=redis)
