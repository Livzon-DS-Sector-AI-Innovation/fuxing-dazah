"""直读视图进程内 TTL 缓存（hazard-id-direct，性能例外落档）。

性能例外（spec D4 预授权条款，总计划风险表预案）：探针全量 594 行 2 页实测
3.68s，超 <2s 验收线（msds 连发 2.73s 触发先例）——按预案加短 TTL 缓存兜住
窗口内重复请求（key_risk_op/knowledge/msds/oh 同款先例）。

- 非 strict 路径（Agent 查询）：命中 TTL 窗口直接返回缓存列表浅拷贝（视图
  对象共享、只读约定——query 层只读视图，过滤/排序产生新列表；department
  由查询层现算注入，不落视图）；过期或首次则拉取并回填；
- strict=True（验证比对）恒绕过缓存强制拉取；
- 拉取失败按 reader 的 strict 语义向上抛（TTL 过期 + Bitable 不可达 = 请求
  失败，与 legacy 镜像库不可达同级别）；
- 单事件循环内无锁：并发 miss 最坏重复拉取一次，无一致性问题。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

__all__ = ["CachedHazardIdReader"]


@dataclass
class _Entry:
    at: float
    views: list[Any]


class CachedHazardIdReader:
    """HazardIdDirectReader 协议的缓存包装（单表缓存；ttl_seconds<=0 直通）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entry: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._entry is not None

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        if strict:
            return list(await self._inner.fetch_all(strict=True))
        if self._ttl <= 0:
            return list(await self._inner.fetch_all(strict=False))
        now = time.monotonic()
        if self._entry is not None and now - self._entry.at < self._ttl:
            return list(self._entry.views)
        fetched: list[Any] = await self._inner.fetch_all(strict=False)
        self._entry = _Entry(at=now, views=fetched)
        return list(fetched)
