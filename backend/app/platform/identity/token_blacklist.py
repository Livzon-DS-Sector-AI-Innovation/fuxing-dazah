"""JWT 吊销黑名单（登出即时失效）。

以 jti 为键写入 Redis，TTL 设为 token 剩余寿命，到期自动清理。
Redis 不可用时降级放行（与权限缓存降级哲学一致：基础设施故障不阻断认证），
代价是 Redis 故障期间的登出不生效，靠 WARNING 日志暴露。
"""

import logging
import time

from redis.exceptions import RedisError

from app.core.redis import cache_get, cache_set

logger = logging.getLogger(__name__)

_BLACKLIST_PREFIX = "jwt_blacklist"


def _key(jti: str) -> str:
    return f"{_BLACKLIST_PREFIX}:{jti}"


async def revoke_token(jti: str, exp: int) -> None:
    """吊销 token：黑名单 TTL = token 剩余寿命。"""
    remaining = max(1, int(exp - time.time()))
    try:
        await cache_set(_key(jti), "1", ex=remaining)
    except RedisError:
        logger.warning(
            "Token revocation skipped (Redis unavailable), jti=%s", jti,
        )


async def is_token_revoked(jti: str) -> bool:
    """查询 jti 是否已吊销。Redis 故障时放行（降级不阻断认证）。"""
    try:
        return await cache_get(_key(jti)) is not None
    except RedisError:
        logger.warning("Blacklist check skipped (Redis unavailable), jti=%s", jti)
        return False
