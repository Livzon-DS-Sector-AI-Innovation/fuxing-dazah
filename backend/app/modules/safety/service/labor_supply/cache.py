"""直读视图进程内 TTL 缓存（labor_supply，仿 oh_direct/cache.py）。

产品目录 102 行 / 配备标准 254 行，页面+agent+档案三处消费——TTL 窗口内
重复请求直接回放缓存列表浅拷贝（视图对象只读约定）。strict=True（验证/
对账）恒绕过；ttl_seconds<=0 直通（config 零感知读取，0 真实生效）。

拉取失败**不上缓存不吞错**：inner fetch 恒 strict（Bitable 不可达 →
异常上抛由调用方降级），残缺/空结果不会被缓存进 TTL 窗口。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

__all__ = ["CachedLaborReader"]


@dataclass
class _Entry:
    at: float
    views: list[Any]


class CachedLaborReader:
    """LaborSupplyReader 协议的缓存包装（两 fetch 各自缓存）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._products: _Entry | None = None
        self._standards: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._products is not None or self._standards is not None

    async def _fetch(
        self,
        slot_name: str,
        fetch: Any,
        *,
        strict: bool = False,
    ) -> list[Any]:
        if strict or self._ttl <= 0:
            return list(await fetch())
        entry = getattr(self, slot_name)
        now = time.monotonic()
        if entry is not None and now - entry.at < self._ttl:
            return list(entry.views)
        fetched: list[Any] = await fetch()
        setattr(self, slot_name, _Entry(at=now, views=fetched))
        return list(fetched)

    async def fetch_products(self, *, strict: bool = False) -> list[Any]:
        return await self._fetch(
            "_products", self._inner.fetch_products, strict=strict,
        )

    async def fetch_position_standards(self, *, strict: bool = False) -> list[Any]:
        return await self._fetch(
            "_standards", self._inner.fetch_position_standards, strict=strict,
        )
