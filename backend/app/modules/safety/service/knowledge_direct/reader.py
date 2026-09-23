"""knowledge 两表直读读取器（Ticket 03）。

双表（kind=collection 安全法规标准 817 行 / collection_env 环保法规标准 12 行，
探针 2026-09-23）asyncio.gather 并发全量拉取：

1. KnowledgeDirectReader 协议：工具注入点，测试用替身（替身必须实现 strict
   参数，mypy 结构化检查口径）。
2. KnowledgeBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   Bitable 行删除即物理消失，直读天然不含已删行（镜像 is_deleted 仅平台侧）。
3. strict 两态：False（查询容错：单表失败跳过、返回另一表已拉部分，gotchas#7）、
   True（验证比对：任一表失败聚合上抛，且恒绕过 TTL 缓存强制拉取）。
4. open_reader() 返回模块级单例 CachedReader（spec D4 性能例外条款触发：
   双表并发实测冷 2.30-2.88s/热 3.10s 超 2s 线 → TTL 60s 缓存，key_risk_op
   同款先例；strict 验证路径不受缓存影响）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.knowledge_direct import config as direct_config
from app.modules.safety.service.knowledge_direct.cache import CachedReader
from app.modules.safety.service.knowledge_direct.views import (
    KnowledgeArticleView,
    view_from_record,
)

__all__ = [
    "KnowledgeBitableReader",
    "KnowledgeDirectReader",
    "open_reader",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class KnowledgeDirectReader(Protocol):
    """域级读取协议：一次调用返回两表全量活行视图（对齐工具查询基面）。

    strict 语义照前域（默认 False）：查询容错（单表失败跳过），
    验证比对显式传 strict=True（失败上抛）。
    """

    async def fetch_all(self, *, strict: bool = False) -> list[KnowledgeArticleView]: ...


class KnowledgeBitableReader:
    """法规标准两表直读读取器真实实现（client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        collection_client: bd_reader.BitablePageClient,
        env_client: bd_reader.BitablePageClient,
        *,
        collection_table_id: str | None = None,
        env_table_id: str | None = None,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._clients = {
            "collection": (collection_client, collection_table_id),
            "collection_env": (env_client, env_table_id),
        }
        self._page_size = page_size

    async def fetch_all(self, *, strict: bool = False) -> list[KnowledgeArticleView]:
        if strict:
            results = await asyncio.gather(
                *(self._fetch_one(kind, strict=True) for kind in self._clients),
            )
            return [v for part in results for v in part]
        # 查询容错：单表失败记日志跳过（gotchas#7），另一表结果照常返回
        parts = await asyncio.gather(
            *(self._fetch_one(kind, strict=False) for kind in self._clients),
            return_exceptions=True,
        )
        views: list[KnowledgeArticleView] = []
        for kind, part in zip(self._clients, parts):
            if isinstance(part, BaseException):
                logger.warning("knowledge 直读 %s 表拉取失败，跳过: %s", kind, part)
                continue
            views.extend(part)
        return views

    async def _fetch_one(self, kind: str, *, strict: bool) -> list[KnowledgeArticleView]:
        client, table_id = self._clients[kind]
        records = await bd_reader.fetch_all_records(
            client,
            table_id=table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[KnowledgeArticleView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            views.append(view_from_record(record_id, kind, r.get("fields") or {}))
        return views


# 模块级单例（TTL 缓存须跨工具调用存活；key_risk_op _shared_reader 同款）
_shared_reader: KnowledgeDirectReader | None = None


def open_reader() -> KnowledgeDirectReader:
    """真实组装（模块级单例——TTL 缓存须跨工具调用存活；工厂形态对齐前域惯例）。

    registry 域 key 为 "knowledge"，kind=collection（安全法规标准）+
    collection_env（环保法规标准），共用同一 app_token 按 table_id 区分。
    未配置/停用抛 BitableConfigError。
    """
    global _shared_reader
    if _shared_reader is None:
        _shared_reader = CachedReader(
            KnowledgeBitableReader(
                bd_reader.resolve_client("knowledge", "collection"),
                bd_reader.resolve_client("knowledge", "collection_env"),
            ),
            ttl_seconds=direct_config.cache_ttl_seconds(),
        )
    return _shared_reader
