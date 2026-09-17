"""底座 per-record 分布式锁（Redis SET NX EX）。

与 hazard_direct 既有实现逐字一致：

- key = safety:<domain>:direct:lock:<record_id>（domain 小写）
- SET NX EX ttl：抢到 = True；抢不到 = False，调用方应跳过该记录
- Redis 不可用时**降级不阻塞**：yield True + warning（局部故障不放大成任务失败）
- 正常结束后释放锁；释放失败只记 debug（TTL 会兜底过期）

设计说明：本模块只依赖标准库，Redis 客户端由调用方注入（域包传自己的
redis_client），因此底座 import 图保持干净、测试可注入假 Redis。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RedisLike(Protocol):
    """只用到 SET NX EX 与 DELETE 两个方法的最小 Redis 协议。"""

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> Any: ...

    async def delete(self, key: str) -> Any: ...


def record_lock_key(domain: str, record_id: str) -> str:
    """per-record 锁 key（与 hazard_direct 既有 key 逐字一致）。"""
    return f"safety:{domain.lower()}:direct:lock:{record_id}"


@asynccontextmanager
async def record_lock(
    record_id: str,
    *,
    domain: str,
    ttl_seconds: int,
    redis: RedisLike,
) -> AsyncIterator[bool]:
    """按记录加锁（Redis SET NX EX）。

    yield True = 抢到锁；False = 已被其他轮次 / 实例处理，调用方应跳过。
    Redis 不可用时降级为「不阻塞」并 yield True（与既有实现一致）。
    """
    key = record_lock_key(domain, record_id)
    try:
        acquired = bool(await redis.set(key, "1", ex=ttl_seconds, nx=True))
    except Exception:
        logger.warning(
            "Redis 不可用，跳过记录锁: record_id=%s", record_id, exc_info=True
        )
        acquired = True

    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis.delete(key)
            except Exception:
                logger.debug("释放记录锁失败: record_id=%s", record_id, exc_info=True)
