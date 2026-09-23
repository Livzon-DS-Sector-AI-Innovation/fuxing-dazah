"""hazard_id 直读读取器（Ticket 03）。

单表（kind=identification 危险源辨识自动化表，survey_hazard_id 2026-09-23
实测 594 行 / 2 页 / 3.68s，Q6=A 全量）：

1. HazardIdDirectReader 协议：工具注入点，测试用替身（替身必须实现全部
   方法含 strict 参数，mypy 结构化检查口径）；
2. HazardIdBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   **恒传 automatic_fields=True** 取 created_time 系统字段（排序键，spec D5
   受控偏差：legacy created_at desc → Bitable created_time desc，594/594
   全覆盖）；无 fid 行丢弃；
3. strict 两态：True（验证比对：API 失败上抛）；False（查询路径：底座按
   「返回已拉到的部分」旧口径）；
4. open_reader() 返回模块级单例 CachedHazardIdReader（spec D4 预授权条款：
   全量实测 3.68s > 2s 验收线 → TTL 60s 缓存，msds/knowledge/oh 同款先例；
   strict 验证路径不受缓存影响）。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.hazard_id_direct import config as direct_config
from app.modules.safety.service.hazard_id_direct.cache import CachedHazardIdReader
from app.modules.safety.service.hazard_id_direct.views import (
    HazardIdentificationView,
    view_from_record,
)

__all__ = [
    "HazardIdBitableReader",
    "HazardIdDirectReader",
    "open_reader",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class HazardIdDirectReader(Protocol):
    """域级读取协议：一次调用返回单表全量行视图（对齐工具查询基面）。"""

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[HazardIdentificationView]: ...


class HazardIdBitableReader:
    """hazard_id 单表直读读取器真实实现（client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        client: bd_reader.BitablePageClient,
        *,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._client = client
        self._page_size = page_size

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[HazardIdentificationView]:
        records = await bd_reader.fetch_all_records(
            self._client,
            page_size=self._page_size,
            strict=strict,
            automatic_fields=True,
        )
        views: list[HazardIdentificationView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            created = r.get("created_time")
            views.append(view_from_record(
                record_id,
                r.get("fields") or {},
                created_time_ms=(
                    int(created) if isinstance(created, (int, float)) else None
                ),
            ))
        return views


# 模块级单例（TTL 缓存须跨工具调用存活；D4 条款触发，knowledge/msds/oh 同款）
_shared_reader: HazardIdDirectReader | None = None


def open_reader() -> HazardIdDirectReader:
    """真实组装（模块级单例；registry 域 key 为 "hazard_id"，kind=
    identification）。未配置/停用抛 BitableConfigError。"""
    global _shared_reader
    if _shared_reader is None:
        _shared_reader = CachedHazardIdReader(
            HazardIdBitableReader(
                bd_reader.resolve_client("hazard_id", "identification"),
            ),
            ttl_seconds=direct_config.cache_ttl_seconds(),
        )
    return _shared_reader
