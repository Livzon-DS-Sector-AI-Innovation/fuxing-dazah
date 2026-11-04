"""直读 TTL 缓存（仿 safety key_risk_op_direct/cache.py）。

进程内单 Entry：命中返回浅拷贝列表（视图对象只读共享）；ttl≤0 直通；
force=True 供预热任务绕过。单事件循环内无锁——并发 miss 最坏重复拉一次。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class DirectCache(Generic[T]):
    """一个直读域一个实例（stock / master / movements）。"""

    def __init__(self, ttl_seconds: Callable[[], int]) -> None:
        self._ttl_seconds = ttl_seconds
        self._entry: tuple[float, list[T]] | None = None

    async def get(
        self,
        loader: Callable[[], Awaitable[list[T]]],
        *,
        force: bool = False,
    ) -> list[T]:
        ttl = self._ttl_seconds()
        now = time.monotonic()
        if (
            not force
            and ttl > 0
            and self._entry is not None
            and now - self._entry[0] < ttl
        ):
            return list(self._entry[1])
        views = await loader()
        self._entry = (time.monotonic(), views)
        return list(views)

    def invalidate(self) -> None:
        """失效（连接坐标/开关变更后调用）。"""
        self._entry = None
