"""cert 直读视图进程内 TTL 缓存（仿 key_risk_op_direct/cache.py）。

驾驶舱 /safety/overview 聚合对 cert 域取 summary + 30 天明细两次派生，
且 3 kind 表全量拉取无窗口下推——非 strict 路径（查询/统计/驾驶舱）命中
TTL 窗口直接返回缓存列表浅拷贝（视图对象共享、只读约定）；
strict=True（预警编排）恒绕过缓存强制拉取；单事件循环内无锁
（并发 miss 最坏重复拉取一次，无一致性问题）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.modules.safety.service.cert_direct.reader import CertWarningView

__all__ = ["CachedCertReader"]


@dataclass
class _Entry:
    at: float
    views: list[CertWarningView]


class CachedCertReader:
    """CertRecordsReader 协议的缓存包装（ttl_seconds<=0 时直通）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entry: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._entry is not None

    async def get_all_active(self, *, strict: bool = False) -> list[CertWarningView]:
        if strict:
            views: list[CertWarningView] = await self._inner.get_all_active(strict=True)
            return views
        if self._ttl <= 0:
            passthrough: list[CertWarningView] = await self._inner.get_all_active(
                strict=False,
            )
            return passthrough
        now = time.monotonic()
        if self._entry is not None and now - self._entry.at < self._ttl:
            return list(self._entry.views)
        fetched: list[CertWarningView] = await self._inner.get_all_active(strict=False)
        self._entry = _Entry(at=now, views=fetched)
        return list(fetched)
