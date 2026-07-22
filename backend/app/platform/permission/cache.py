"""Permission Redis cache layer."""

import json

from app.core.redis import cache_delete, cache_get, cache_set, get_redis

CACHE_PREFIX = "user_perms"
CACHE_TTL = 300  # 5 minutes


async def get_cached_permissions(user_id: str) -> set[str] | None:
    """从 Redis 获取用户权限集合。返回 None 表示缓存未命中。"""
    key = f"{CACHE_PREFIX}:{user_id}"
    data = await cache_get(key)
    if data is None:
        return None
    return set(json.loads(data))


async def set_cached_permissions(user_id: str, permissions: set[str]) -> None:
    """将用户权限集合写入 Redis 缓存。"""
    key = f"{CACHE_PREFIX}:{user_id}"
    await cache_set(key, json.dumps(list(permissions)), ex=CACHE_TTL)


async def invalidate_user_cache(user_id: str) -> None:
    """清除指定用户的权限缓存。"""
    key = f"{CACHE_PREFIX}:{user_id}"
    await cache_delete(key)


async def invalidate_all_caches() -> None:
    """清除所有用户的权限缓存（慎用）。"""
    redis = await get_redis()
    keys: list[str] = []
    async for key in redis.scan_iter(match=f"{CACHE_PREFIX}:*"):
        keys.append(key)
    if keys:
        for k in keys:
            await cache_delete(k)
