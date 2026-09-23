"""msds 台账直读读取器（Ticket 02）。

单表（kind=registry，MSDS 收录台账表，探针 2026-09-23 共 71 行）全量拉取：

1. MsdsDirectReader 协议：工具注入点，测试用替身（替身必须实现 strict
   参数，mypy 结构化检查口径）。
2. MsdsBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   Bitable 行删除即物理消失，直读天然不含已删行（镜像 is_deleted 仅平台侧）。
3. strict 两态：True（验证比对：API 失败上抛）；False（查询路径：底座按
   「返回已拉到的部分」旧口径，单表域无「跳过另一表」可言，两态差异由底座
   fetch_all_records 自然承载）。
4. open_reader() 返回模块级单例 CachedReader（spec D4 预授权条款触发：
   探针 71 行单页 1.01s，但 verify 连发全量实测 2.73s 超线 → TTL 60s 缓存，
   knowledge/key_risk_op 同款先例；strict 验证路径不受缓存影响）。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.msds_direct import config as direct_config
from app.modules.safety.service.msds_direct.cache import CachedReader
from app.modules.safety.service.msds_direct.views import (
    MsdsDocumentView,
    view_from_record,
)

__all__ = [
    "MsdsBitableReader",
    "MsdsDirectReader",
    "open_reader",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class MsdsDirectReader(Protocol):
    """域级读取协议：一次调用返回台账表全量活行视图（对齐工具查询基面）。"""

    async def fetch_all(self, *, strict: bool = False) -> list[MsdsDocumentView]: ...


class MsdsBitableReader:
    """MSDS 收录台账表直读读取器真实实现（client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        registry_client: bd_reader.BitablePageClient,
        *,
        table_id: str | None = None,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._client = registry_client
        self._table_id = table_id
        self._page_size = page_size

    async def fetch_all(self, *, strict: bool = False) -> list[MsdsDocumentView]:
        records = await bd_reader.fetch_all_records(
            self._client,
            table_id=self._table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[MsdsDocumentView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            views.append(view_from_record(record_id, r.get("fields") or {}))
        return views


# 模块级单例（TTL 缓存须跨工具调用存活；D4 条款触发，knowledge 同款）
_shared_reader: MsdsDirectReader | None = None


def open_reader() -> MsdsDirectReader:
    """真实组装（模块级单例——TTL 缓存须跨工具调用存活；registry 域 key
    为 "msds"，kind=registry）。未配置/停用抛 BitableConfigError。
    """
    global _shared_reader
    if _shared_reader is None:
        _shared_reader = CachedReader(
            MsdsBitableReader(
                bd_reader.resolve_client("msds", "registry"),
            ),
            ttl_seconds=direct_config.cache_ttl_seconds(),
        )
    return _shared_reader
