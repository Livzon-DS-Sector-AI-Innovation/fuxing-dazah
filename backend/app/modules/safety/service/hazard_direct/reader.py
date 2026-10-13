"""隐患直读 — 页面/看板查询用缓存读取器。

全量拉取主表（自动翻页）→ ``to_view`` 映射 → 进程内 TTL 缓存，
供台账列表 / 统计 / 总览采集器共用一次拉取（key_risk_op CachedReader 同款模式）。

- TTL 可配 ``SAFETY_HAZARD_DIRECT_CACHE_TTL_SECONDS``（默认 60，0=关）；
- ``strict=True`` 绕过缓存（导出/对账场景）；
- 查询失败向上抛 ``BitableQueryError``（页面显式报错，不静默空列表）。
"""

from __future__ import annotations

import time
from typing import Any, cast

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.hazard_direct import bitable_repo, config

_cached: dict[str, Any] = {"ts": 0.0, "views": []}


class CachedHazardReader:
    """隐患主表全量视图的 TTL 缓存读取器。"""

    def __init__(self, client: SafetyBitableClient | None = None) -> None:
        self._client = client

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        """全量 HazardView（异常占位记录已排除；缓存命中直接返回）。"""
        ttl = config.cache_ttl_seconds()
        now = time.monotonic()
        if not strict and ttl > 0 and _cached["views"] and now - _cached["ts"] < ttl:
            return cast("list[Any]", _cached["views"])

        client = self._client or SafetyBitableClient()
        records = await client.list_all_records(automatic_fields=True, page_size=500, strict=True)
        views = []
        for rec in records:
            desc = (bitable_repo.f_text(rec.get("fields") or {}, bitable_repo.F_DESC) or "").strip()
            if not desc or desc == "待AI填写":
                continue  # 异常占位记录（与 query_hazards 同口径）
            views.append(bitable_repo.to_view(rec))
        if ttl > 0:
            _cached["ts"] = now
            _cached["views"] = views
        return views


def open_reader() -> CachedHazardReader:
    """模块级单例（页面/看板/采集器共用同一份缓存）。"""
    return _READER


_READER = CachedHazardReader()
