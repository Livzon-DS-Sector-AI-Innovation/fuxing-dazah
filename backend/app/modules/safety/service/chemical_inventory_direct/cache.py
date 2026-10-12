"""危化品库存直读视图进程内 TTL 缓存（仿 key_risk_op_direct/cache.py）。

库存快照表全量拉取无时间窗口概念；驾驶舱 /safety/overview 聚合取 stats +
超储明细两路都走 fetch_all——非 strict 路径（查询/统计/驾驶舱）命中 TTL
直接返回缓存列表浅拷贝（视图对象共享、只读约定）；
strict=True（日报编排/风险扫描）恒绕过缓存强制拉取；单事件循环内无锁。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.modules.safety.service.chemical_inventory_direct.views import InventoryView

__all__ = ["CachedInventoryReader"]


@dataclass
class _Entry:
    at: float
    views: list[InventoryView]


class CachedInventoryReader:
    """InventoryRecordsReader 协议的缓存包装（ttl_seconds<=0 时直通）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entry: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._entry is not None

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]:
        if strict:
            views: list[InventoryView] = await self._inner.fetch_all(strict=True)
            return views
        if self._ttl <= 0:
            passthrough: list[InventoryView] = await self._inner.fetch_all(strict=False)
            return passthrough
        now = time.monotonic()
        if self._entry is not None and now - self._entry.at < self._ttl:
            return list(self._entry.views)
        fetched: list[InventoryView] = await self._inner.fetch_all(strict=False)
        self._entry = _Entry(at=now, views=fetched)
        return list(fetched)
