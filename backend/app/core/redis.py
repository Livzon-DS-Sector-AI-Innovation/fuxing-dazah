from typing import cast

import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()

redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)


async def get_redis() -> redis.Redis:
    return redis_client


async def cache_get(key: str) -> str | None:
    return cast(str | None, await redis_client.get(key))


async def cache_set(key: str, value: str, ex: int = 3600) -> None:
    await redis_client.set(key, value, ex=ex)


async def cache_delete(key: str) -> None:
    await redis_client.delete(key)


async def acquire_lock(key: str, timeout: int = 10) -> bool:
    return bool(await redis_client.set(f"lock:{key}", "1", ex=timeout, nx=True))


async def release_lock(key: str) -> None:
    await redis_client.delete(f"lock:{key}")
