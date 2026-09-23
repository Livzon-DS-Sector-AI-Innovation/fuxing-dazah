"""knowledge 直读侧清单查询（Ticket 03）——单语义，Agent 工具专用。

``latest_regulations`` 忠实复刻 read_tools.query_latest_regulations 的 legacy
镜像语义（spec D5，含两个既有 quirk，不修不扩）：

- cutoff 过滤：input_date >= today-days（等价 legacy created_at >= cutoff，
  探针实证「入库日期」829/829 全覆盖）；
- 排序：input_date desc NULLS LAST（等价 created_at desc；同日内顺序差异为
  受控偏差——PG 有亚秒精度、入库日期为日期粒度）；
- **先截断 limit 再过滤**：legacy 先 SQL LIMIT 再 Python 过滤 impact_level /
  business_domain，过滤后条数可少于 limit——直读按同一顺序复刻；
- impact_level：解析 notes「影响等级: 高/中/低」子串（直读 notes 与镜像同源，
  均来自 Bitable 备注）；
- business_domain：照 legacy `business_domain not in category` 字面复刻——
  category 是映射后英文枚举，中文领域名永不命中 → 传参时恒空（既有缺陷
  忠实复刻不修，修复需另票拍板 DOMAIN_TO_CATEGORY 语义）。
"""

from __future__ import annotations

import functools
from datetime import date, timedelta
from typing import Any

from app.modules.safety.service.knowledge_direct.views import (
    KnowledgeArticleView,
)

__all__ = ["latest_regulations"]

# 与 legacy 工具体逐字同款的影响等级解析子串
_IMPACT_MARKS = (("高", "影响等级: 高"), ("中", "影响等级: 中"), ("低", "影响等级: 低"))


def _parse_impact_level(notes: str | None) -> str:
    text = notes or ""
    for level, mark in _IMPACT_MARKS:
        if mark in text:
            return level
    return ""


def _input_date_desc_nulls_last(
    a: KnowledgeArticleView, b: KnowledgeArticleView,
) -> int:
    """input_date desc + NULLS LAST（emergency_drill D3 同款比较器）。"""
    if a.input_date is None and b.input_date is None:
        return 0
    if a.input_date is None:
        return 1
    if b.input_date is None:
        return -1
    if a.input_date == b.input_date:
        return 0
    return -1 if a.input_date > b.input_date else 1


def latest_regulations(
    views: list[KnowledgeArticleView],
    *,
    limit: int = 10,
    days: int = 30,
    impact_level: str = "",
    business_domain: str = "",
) -> dict[str, Any]:
    """最近法规清单（legacy query_latest_regulations 等价内存实现）。"""
    cutoff = date.today() - timedelta(days=days)
    recent = [
        v for v in views
        if v.input_date is not None and v.input_date >= cutoff
    ]
    recent.sort(key=functools.cmp_to_key(_input_date_desc_nulls_last))
    # legacy：SQL LIMIT 在前 → Python 过滤在后（quirk 忠实复刻）
    truncated = recent[: max(0, limit)]

    items: list[dict[str, Any]] = []
    for v in truncated:
        item_level = _parse_impact_level(v.notes)
        if impact_level and item_level != impact_level:
            continue
        if business_domain and business_domain not in (v.category or ""):
            continue
        items.append({
            "id": v.id,
            "article_no": v.article_no,
            "title": v.title,
            "category": v.category,
            "impact_level": item_level or None,
            "publish_date": v.publish_date.isoformat() if v.publish_date else None,
            "status": v.status,
            "source": v.source,
        })
    return {"items": items, "total": len(items)}
