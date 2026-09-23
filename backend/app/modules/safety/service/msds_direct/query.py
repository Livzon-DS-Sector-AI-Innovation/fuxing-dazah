"""msds 直读侧台账查询（Ticket 02）——单语义，Agent 工具专用。

``msds_documents`` 忠实复刻 service/msds.MsdsService.list_documents 的 legacy
镜像语义（spec D5；legacy 过滤/分页全在 SQL WHERE/OFFSET-LIMIT，无
「先截断后过滤」quirk，干净复刻）：

- 过滤：name/cas_no 大小写不敏感包含（等价 ilike %x%；两者 AND 组合）；
- 排序：source_date desc NULLS LAST（D3 受控偏差：legacy created_at=镜像行
  插入时间不可直读；探针「日期」71/71 全覆盖=业务日期键；同日内顺序差异
  落档）；
- 分页：skip/limit 应用侧内存分页（等价 OFFSET/LIMIT）；total=过滤后全量
  计数（等价 SQL count，非页大小）；
- 输出：item 键与 read_tools.query_msds_documents 现输出逐字一致；
  review_status/archive_status 为视图常量 pending（审核流未上线，与镜像
  实际值一致，spec §4.3）。
"""

from __future__ import annotations

import functools
from typing import Any

from app.modules.safety.service.msds_direct.views import MsdsDocumentView

__all__ = ["msds_documents"]

# 与 legacy 工具体逐字同款的输出键集
_ITEM_KEYS = (
    "id", "name", "cas_no", "molecular_formula", "un_no",
    "hazard_statement", "appearance", "flash_point", "relative_density",
    "pc_twa", "health_hazard", "first_aid", "review_status", "archive_status",
)


def _contains(value: str | None, keyword: str) -> bool:
    """等价 ORM ``col.ilike(f"%{keyword}%")``：大小写不敏感包含。"""
    return value is not None and keyword.lower() in value.lower()


def _source_date_desc_nulls_last(a: MsdsDocumentView, b: MsdsDocumentView) -> int:
    """source_date desc + NULLS LAST（emergency_drill D3 同款比较器）。"""
    if a.source_date is None and b.source_date is None:
        return 0
    if a.source_date is None:
        return 1
    if b.source_date is None:
        return -1
    if a.source_date == b.source_date:
        return 0
    return -1 if a.source_date > b.source_date else 1


def msds_documents(
    views: list[MsdsDocumentView],
    *,
    name: str | None = None,
    cas_no: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """MSDS 台账列表（legacy list_documents 等价内存实现）。"""
    filtered = [
        v for v in views
        if (not name or _contains(v.name, name))
        and (not cas_no or _contains(v.cas_no, cas_no))
    ]
    filtered.sort(key=functools.cmp_to_key(_source_date_desc_nulls_last))
    window = filtered[max(0, skip): max(0, skip) + max(0, limit)]

    items: list[dict[str, Any]] = [
        {key: getattr(v, key) for key in _ITEM_KEYS} for v in window
    ]
    return items, len(filtered)
