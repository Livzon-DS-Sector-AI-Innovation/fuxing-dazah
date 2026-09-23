"""oh 直读读取器（Ticket 02）。

两表（kind=position 岗位信息表探针 440 行 / kind=hazard_factor 危害因素 PPE 表
33 行，survey_oh 2026-09-23）全量拉取：

1. OhDirectReader 协议：工具注入点，测试用替身（替身必须实现全部方法含
   strict 参数，mypy 结构化检查口径）。
2. OhBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   Bitable 行删除即物理消失，直读天然不含已删行（镜像 is_deleted 仅平台侧）；
   跳行规则由 view_from_record 返回 None 承载（spec D7）。
3. strict 两态：True（验证比对：API 失败上抛）；False（查询路径：底座按
   「返回已拉到的部分」旧口径）。
4. open_reader() 返回模块级单例 CachedOhReader（spec D4 预授权条款：
   探针单页 0.93s/1.15s，连发可能触 <2s 验收线 → TTL 60s 缓存，msds/
   knowledge/key_risk_op 同款先例；strict 验证路径不受缓存影响）。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.oh_direct import config as direct_config
from app.modules.safety.service.oh_direct.cache import CachedOhReader
from app.modules.safety.service.oh_direct.views import (
    OhHazardFactorView,
    OhPositionView,
    hazard_factor_view_from_record,
    position_view_from_record,
)

__all__ = [
    "OhBitableReader",
    "OhDirectReader",
    "open_reader",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class OhDirectReader(Protocol):
    """域级读取协议：一次调用返回单表全量活行视图（对齐工具查询基面）。"""

    async def fetch_positions(
        self, *, strict: bool = False
    ) -> list[OhPositionView]: ...

    async def fetch_factors(
        self, *, strict: bool = False
    ) -> list[OhHazardFactorView]: ...


class OhBitableReader:
    """oh 两表直读读取器真实实现（client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        position_client: bd_reader.BitablePageClient,
        factor_client: bd_reader.BitablePageClient,
        *,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._position_client = position_client
        self._factor_client = factor_client
        self._page_size = page_size

    async def _fetch(
        self,
        client: bd_reader.BitablePageClient,
        view_from: Any,
        *,
        strict: bool = False,
    ) -> list[Any]:
        records = await bd_reader.fetch_all_records(
            client,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[Any] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            view = view_from(record_id, r.get("fields") or {})
            if view is not None:
                views.append(view)
        return views

    async def fetch_positions(
        self, *, strict: bool = False
    ) -> list[OhPositionView]:
        views: list[OhPositionView] = await self._fetch(
            self._position_client,
            position_view_from_record,
            strict=strict,
        )
        return views

    async def fetch_factors(
        self, *, strict: bool = False
    ) -> list[OhHazardFactorView]:
        views: list[OhHazardFactorView] = await self._fetch(
            self._factor_client,
            hazard_factor_view_from_record,
            strict=strict,
        )
        return views


# 模块级单例（TTL 缓存须跨工具调用存活；D4 条款触发，knowledge 同款）
_shared_reader: OhDirectReader | None = None


def open_reader() -> OhDirectReader:
    """真实组装（模块级单例——TTL 缓存须跨工具调用存活；registry 域 key
    为 "oh"，kind=position / hazard_factor）。未配置/停用抛 BitableConfigError。
    """
    global _shared_reader
    if _shared_reader is None:
        _shared_reader = CachedOhReader(
            OhBitableReader(
                bd_reader.resolve_client("oh", "position"),
                bd_reader.resolve_client("oh", "hazard_factor"),
            ),
            ttl_seconds=direct_config.cache_ttl_seconds(),
        )
    return _shared_reader
