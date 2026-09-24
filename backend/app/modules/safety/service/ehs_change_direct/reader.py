"""ehs_change 直读读取器（Ticket 02）。

两表（kind=approval 变更审批 268 行 / kind=acceptance 变更验收 224 行，
survey_ehs_change 2026-09-24 实测合计 492 行 << 3000，Q6=A 全量）：

1. EhsChangeDirectReader 协议：工具注入点，测试用替身（替身必须实现
   全部方法含 strict 参数，mypy 结构化检查口径）；
2. EhsChangeBitableReader：底座批量 search 分页全量（禁止逐条
   get_record）；**恒传 automatic_fields=True** 取 created_time 系统字段
   （排序键，spec D3）；两表 asyncio.gather 并发拉取（串行实测约 2.3s，
   并发后约 1.3s，再叠 TTL 兜住 <2s 验收线）；mapper 返 None
   （「已删除」态）跳行；
3. strict 两态：True（验证比对：任一表失败上抛）；False（查询路径：
   底座按「返回已拉到的部分」旧口径）；
4. open_reader() 返回模块级单例 CachedEhsChangeReader（spec D4 预授权
   条款；strict 验证路径不受缓存影响）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.ehs_change_direct import config as direct_config
from app.modules.safety.service.ehs_change_direct.cache import CachedEhsChangeReader
from app.modules.safety.service.ehs_change_direct.views import (
    EhsChangeView,
    view_from_record,
)

__all__ = [
    "EhsChangeBitableReader",
    "EhsChangeDirectReader",
    "open_reader",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class EhsChangeDirectReader(Protocol):
    """域级读取协议：一次调用返回两表合并全量行视图（台账并集口径，spec D6）。"""

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[EhsChangeView]: ...


async def _fetch_kind(
    client: bd_reader.BitablePageClient,
    kind: str,
    *,
    page_size: int,
    strict: bool,
) -> list[EhsChangeView]:
    records = await bd_reader.fetch_all_records(
        client, page_size=page_size, strict=strict, automatic_fields=True,
    )
    views: list[EhsChangeView] = []
    for r in records:
        record_id = str(r.get("record_id") or "")
        if not record_id:
            continue
        created = r.get("created_time")
        view = view_from_record(
            kind,
            record_id,
            r.get("fields") or {},
            created_time_ms=(
                int(created) if isinstance(created, (int, float)) else None
            ),
        )
        if view is None:
            continue  # 「已删除」态行：镜像同款跳过
        views.append(view)
    return views


class EhsChangeBitableReader:
    """ehs_change 两表直读读取器真实实现（client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        approval_client: bd_reader.BitablePageClient,
        acceptance_client: bd_reader.BitablePageClient,
        *,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._approval_client = approval_client
        self._acceptance_client = acceptance_client
        self._page_size = page_size

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[EhsChangeView]:
        approval_views, acceptance_views = await asyncio.gather(
            _fetch_kind(
                self._approval_client, "approval",
                page_size=self._page_size, strict=strict,
            ),
            _fetch_kind(
                self._acceptance_client, "acceptance",
                page_size=self._page_size, strict=strict,
            ),
        )
        return [*approval_views, *acceptance_views]


# 模块级单例（TTL 缓存须跨工具调用存活；D4 条款触发，knowledge/msds/oh/hazard_id 同款）
_shared_reader: EhsChangeDirectReader | None = None


def open_reader() -> EhsChangeDirectReader:
    """真实组装（模块级单例；registry 域 key 为 "ehs_change"，kind=
    approval/acceptance）。未配置/停用抛 BitableConfigError。"""
    global _shared_reader
    if _shared_reader is None:
        _shared_reader = CachedEhsChangeReader(
            EhsChangeBitableReader(
                bd_reader.resolve_client("ehs_change", "approval"),
                bd_reader.resolve_client("ehs_change", "acceptance"),
            ),
            ttl_seconds=direct_config.cache_ttl_seconds(),
        )
    return _shared_reader
