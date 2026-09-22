"""直读视图进程内 TTL 缓存（key_risk_op-direct Ticket 02）。

性能例外落档（spec §4.2）：全量拉取 1585 行 4 页串行 ~4.9s（page_token 链式无法
并行），超 <2s 验收线——按总计划风险表预案以短 TTL 缓存兜住窗口内重复请求。

- 非 strict 路径（查询/统计/导出/Agent）：命中 TTL 窗口直接返回缓存列表浅拷贝（视图对象共享、只读约定）；
  过期或首次则拉取并回填。
- strict=True（验证比对/编排）恒绕过缓存强制拉取。
- 拉取失败按 reader 的 strict 语义向上抛（TTL 过期 + Bitable 不可达 = 请求失败，
  与 legacy 镜像库不可达同级别）。
- 单事件循环内无锁：并发 miss 最坏重复拉取一次，无一致性问题。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.modules.safety.service.key_risk_op_direct.views import KeyRiskOpView

__all__ = ["CachedReader"]


@dataclass
class _Entry:
    at: float
    views: list[KeyRiskOpView]


class CachedReader:
    """KeyRiskOpRecordsReader 协议的缓存包装（ttl_seconds<=0 时直通）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entry: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._entry is not None

    async def fetch_all(self, *, strict: bool = False) -> list[KeyRiskOpView]:
        if strict:
            views: list[KeyRiskOpView] = await self._inner.fetch_all(strict=True)
            return views
        if self._ttl <= 0:
            passthrough: list[KeyRiskOpView] = await self._inner.fetch_all(strict=False)
            return passthrough
        now = time.monotonic()
        if self._entry is not None and now - self._entry.at < self._ttl:
            return list(self._entry.views)
        fetched: list[KeyRiskOpView] = await self._inner.fetch_all(strict=False)
        self._entry = _Entry(at=now, views=fetched)
        return list(fetched)
