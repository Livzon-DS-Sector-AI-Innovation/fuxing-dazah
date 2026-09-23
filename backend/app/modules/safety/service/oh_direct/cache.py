"""直读视图进程内 TTL 缓存（oh-direct，性能例外落档）。

性能例外（spec D4 预授权条款，总计划风险表预案）：探针两表单页各
0.93s/1.15s，连发可能触 <2s 验收线（msds 连发 2.73s 触发先例）——按预案加
短 TTL 缓存兜住窗口内重复请求（key_risk_op/knowledge/msds 同款先例）。

- 非 strict 路径（Agent 查询）：命中 TTL 窗口直接返回缓存列表浅拷贝（视图
  对象共享、只读约定——query 层只读视图，过滤/排序产生新列表）；两表各自
  独立缓存；过期或首次则拉取并回填。
- strict=True（验证比对）恒绕过缓存强制拉取。
- 拉取失败按 reader 的 strict 语义向上抛（TTL 过期 + Bitable 不可达 = 请求
  失败，与 legacy 镜像库不可达同级别）。
- 单事件循环内无锁：并发 miss 最坏重复拉取一次，无一致性问题。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

__all__ = ["CachedOhReader"]


@dataclass
class _Entry:
    at: float
    views: list[Any]


class CachedOhReader:
    """OhDirectReader 协议的缓存包装（两表各自缓存；ttl_seconds<=0 时直通）。"""

    def __init__(self, inner: Any, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._positions: _Entry | None = None
        self._factors: _Entry | None = None

    @property
    def cached(self) -> bool:
        """当前是否有可复用缓存（测试/观测用）。"""
        return self._positions is not None or self._factors is not None

    async def _fetch(
        self,
        slot_name: str,
        fetch: Any,
        *,
        strict: bool = False,
    ) -> list[Any]:
        if strict:
            return list(await fetch(strict=True))
        if self._ttl <= 0:
            return list(await fetch(strict=False))
        entry = getattr(self, slot_name)
        now = time.monotonic()
        if entry is not None and now - entry.at < self._ttl:
            return list(entry.views)
        fetched: list[Any] = await fetch(strict=False)
        setattr(self, slot_name, _Entry(at=now, views=fetched))
        return list(fetched)

    async def fetch_positions(self, *, strict: bool = False) -> list[Any]:
        return await self._fetch(
            "_positions", self._inner.fetch_positions, strict=strict,
        )

    async def fetch_factors(self, *, strict: bool = False) -> list[Any]:
        return await self._fetch(
            "_factors", self._inner.fetch_factors, strict=strict,
        )
