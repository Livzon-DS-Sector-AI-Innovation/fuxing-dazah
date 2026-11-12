"""登录一次性 code：SSO 回调后 JWT 存 Redis 短期 code，前端 exchange 兑换。

避免 JWT 直接拼在重定向 URL 上（会进浏览器历史、访问日志与 Referer）。
code 特性：120 秒过期、一次性（getdel 原子兑换）、不可猜测。
"""

import secrets

from app.core.redis import get_redis

CODE_PREFIX = "login_code"
CODE_TTL = 120  # 秒


def _key(code: str) -> str:
    return f"{CODE_PREFIX}:{code}"


async def issue_login_code(token: str) -> str:
    """生成一次性 code 并绑定 token，返回 code（供拼入回调 URL）。"""
    code = secrets.token_urlsafe(32)
    redis = await get_redis()
    await redis.set(_key(code), token, ex=CODE_TTL)
    return code


async def exchange_login_code(code: str) -> str | None:
    """原子兑换：返回绑定的 token 并立即使 code 失效；无效/已用/过期返回 None。"""
    redis = await get_redis()
    return await redis.getdel(_key(code))
