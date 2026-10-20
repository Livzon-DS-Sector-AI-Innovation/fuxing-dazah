"""三台账直读 reader（facilities-p1）。

照 visitor_insurance/reader.py 手法：BitablePageClient 注入、strict 全量拉取
（批量 search，绝不逐条读）；差异在本域 3 张表、全列投影（field_names=None，
列名由映射层按表头解析）。页面查询路径包 TTL 300s 进程内缓存（照
cert_direct/cache.py），派发/对账/事件闭环走 strict=True 恒绕过。

未配置连接：resolve_client 抛 BitableConfigError——调用方（API 三态信封 /
调度 no_source / 事件 handler）各自按语义处理，本层绝不静默返回空。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping

from app.modules.safety.facilities.ledger import (
    BIZ_TO_KIND,
    DOMAIN,
    LedgerRowView,
    to_views,
)
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError

logger = logging.getLogger(__name__)

__all__ = ["FacilitiesLedgerReader", "CachedLedgerReader", "open_reader"]

DEFAULT_CACHE_TTL_SECONDS = 300


def kind_of(biz_type: str) -> str:
    return BIZ_TO_KIND[biz_type]


def resolve_client(biz_type: str) -> bd_reader.BitablePageClient:
    """biz_type -> 已配置的 page client（未配置/停用抛 BitableConfigError）。"""
    return bd_reader.resolve_client(DOMAIN, kind_of(biz_type))


def connection_configured(biz_type: str) -> bool:
    """该台账连接是否已登记且启用（调度 no_source 判定用，不抛错）。"""
    conn = bd_reader.store.get_connection(DOMAIN, kind_of(biz_type))
    return conn is not None and conn.enabled


class FacilitiesLedgerReader:
    """三台账读取器真实实现（clients 按 biz_type 注入，测试用替身）。"""

    def __init__(
        self,
        clients: Mapping[str, bd_reader.BitablePageClient] | None = None,
        *,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._clients = clients
        self._page_size = page_size

    def _client(self, biz_type: str) -> bd_reader.BitablePageClient:
        if self._clients is not None:
            client = self._clients.get(biz_type)
            if client is None:
                raise BitableConfigError(
                    f"facilities 台账未配置连接: biz_type={biz_type}"
                )
            return client
        return resolve_client(biz_type)

    async def fetch_ledger(self, biz_type: str, *, strict: bool = True) -> list[LedgerRowView]:
        """单台账全量拉取 → 视图列表（恒 strict：失败上抛，由调用方决定降级/
        no_source/补发语义；缓存与否是 CachedLedgerReader 的职责，与本层无关）。"""
        client = self._client(biz_type)
        records = await bd_reader.fetch_all_records(
            client,
            field_names=None,
            page_size=self._page_size,
            strict=True,
        )
        return to_views(records, biz_type)

    async def fetch_row(
        self, biz_type: str, record_id: str, *, strict: bool = True
    ) -> LedgerRowView | None:
        """单行现读（事件闭环通道用；全量拉取后按 record_id 定位）。"""
        views = await self.fetch_ledger(biz_type, strict=strict)
        for v in views:
            if v.record_id == record_id:
                return v
        return None


class CachedLedgerReader:
    """页面查询路径的 TTL 缓存包装；strict 恒绕过；ttl<=0 直通。

    strict 语义：True=派发/对账/事件通道，绕过缓存直拉；False=页面查询路径，
    命中窗口返回缓存，miss 时**内层仍 strict 拉取**（失败上抛→页面降级，
    失败结果不缓存）。每台账独立缓存项；返回浅拷贝列表（视图对象只读约定，
    照 cert_direct）。
    """

    def __init__(self, inner: FacilitiesLedgerReader, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entries: dict[str, tuple[float, list[LedgerRowView]]] = {}

    async def fetch_ledger(self, biz_type: str, *, strict: bool = True) -> list[LedgerRowView]:
        if strict or self._ttl <= 0:
            return await self._inner.fetch_ledger(biz_type, strict=True)
        now = time.monotonic()
        entry = self._entries.get(biz_type)
        if entry is not None and now - entry[0] < self._ttl:
            return list(entry[1])
        views = await self._inner.fetch_ledger(biz_type, strict=True)
        self._entries[biz_type] = (now, views)
        return list(views)

    async def fetch_row(
        self, biz_type: str, record_id: str, *, strict: bool = True
    ) -> LedgerRowView | None:
        views = await self.fetch_ledger(biz_type, strict=strict)
        for v in views:
            if v.record_id == record_id:
                return v
        return None

    def invalidate(self, biz_type: str | None = None) -> None:
        """失效缓存（连接变更/事件闭环后可显式调用）。"""
        if biz_type is None:
            self._entries.clear()
        else:
            self._entries.pop(biz_type, None)


_shared: CachedLedgerReader | None = None


def open_reader(
    *, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
) -> CachedLedgerReader:
    """真实组装（进程内单例，TTL 缓存跨调用方生效；strict 恒绕过）。"""
    global _shared
    if _shared is None:
        _shared = CachedLedgerReader(FacilitiesLedgerReader(), ttl_seconds=ttl_seconds)
    return _shared


def reset_shared_reader() -> None:
    """测试隔离用：丢弃进程内单例。"""
    global _shared
    _shared = None
