"""危化品库存总表直读读取器（chemical_inventory-direct Ticket 03）。

单表（kind=inventory，462 行级固定行台账）全量拉取，照 cert_direct/reader.py 模式：

1. InventoryRecordsReader 协议：编排/service 双路径统一注入点，测试用替身
   （替身必须实现 strict 参数，mypy 结构化检查口径）。
2. InventoryBitableReader：底座批量 search 分页全量拉取（禁止逐条 get_record），
   「无物料名称/无 record_id 跳过」与镜像 sync_inventory_records_from_bitable 同口径；
   strict 两态：False（查询/统计容错：分页中断返回已拉部分）、
   True（日报编排：失败聚合上抛 RuntimeError → 调度器标 failed 补发）。
3. 连接经配置中心 store 解析（direct base token，无 wiki 解析——探针实证）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.safety.chemical_inventory.enum_maps import _text
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.chemical_inventory_direct.views import (
    InventoryView,
    sort_like_inventory,
    view_from_record_id,
)

__all__ = [
    "InventoryRecordsReader",
    "InventoryBitableReader",
    "open_reader",
]


@runtime_checkable
class InventoryRecordsReader(Protocol):
    """域级读取协议：一次调用返回全量活行视图（对齐镜像 repo.list_all_inventory_records）。

    strict 语义照 cert（默认 False）：查询/统计容错（分页中断返回已拉部分），
    日报编排显式传 strict=True（失败上抛，调度器补发）。
    """

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]: ...


class InventoryBitableReader:
    """总表直读读取器真实实现（单表全量；client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        client: bd_reader.BitablePageClient,
        *,
        table_id: str | None = None,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._client = client
        self._table_id = table_id
        self._page_size = page_size

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]:
        """全量拉取 → 逐行成视图（脏行跳过与镜像同口径）→ 镜像口径排序。"""
        records = await bd_reader.fetch_all_records(
            self._client,
            table_id=self._table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[InventoryView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            fields = r.get("fields") or {}
            if not record_id or not _text(fields.get("物料名称")):
                continue
            views.append(view_from_record_id(record_id, fields))
        return sort_like_inventory(views)


_shared_reader: InventoryRecordsReader | None = None


def open_reader(
    *,
    page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
) -> InventoryRecordsReader:
    """真实组装（进程内单例）：配置中心解析连接 + TTL 缓存层。

    单例使 TTL 缓存跨调用方生效（查询/统计/驾驶舱共享同一缓存窗口；
    日报编排的 strict 拉取恒绕过）。registry 域 key 为小写
    "chemical_inventory"。未配置/停用抛 BitableConfigError。
    """
    global _shared_reader
    if _shared_reader is None:
        client = bd_reader.resolve_client("chemical_inventory", "inventory")
        inner = InventoryBitableReader(client, page_size=page_size)
        from app.modules.safety.service.chemical_inventory_direct.cache import (
            CachedInventoryReader,
        )
        from app.modules.safety.service.chemical_inventory_direct.config import (
            cache_ttl_seconds,
        )

        _shared_reader = CachedInventoryReader(inner, ttl_seconds=cache_ttl_seconds())
    return _shared_reader
