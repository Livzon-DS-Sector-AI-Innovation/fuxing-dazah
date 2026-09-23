"""knowledge 直读视图对象（Ticket 01）。

照 emergency_drill_direct/views.py 模式：

1. KnowledgeArticleView：字段与 SafetyKnowledgeArticle ORM 同名子集
   （query_latest_regulations 消费面）；id = feishu_record_id = recXXX；
   created_at/updated_at 恒 None——PG 审计时间不可直读；直读专有键
   input_date（Bitable「入库日期」列，探针 829/829 全覆盖，语义=入库时间，
   与 legacy created_at 同义，spec D4 过滤/排序键）+ source_kind（两表归因）。
2. view_from_record：映射复用 handler 同一纯函数 ``_map_knowledge_fields``
   （静态、零 IO；KNOWLEDGE_BITABLE_TO_MODEL 8 字段 + CATEGORY_CN_TO_EN /
   STATUS_CN_TO_EN 枚举 + _ms_to_date / _extract_rich_text 同口径），
   article_no 单独直取（handler 回写目标列，探针实证两表暂无此列 → None
   优雅降级，建列后自动有值，spec D3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.modules.safety.feishu.knowledge_bitable_handler import (
    _extract_rich_text,
    _map_knowledge_fields,
    _ms_to_date,
)

__all__ = [
    "KnowledgeArticleView",
    "view_from_record",
]


@dataclass
class KnowledgeArticleView:
    """法规标准行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    feishu_record_id: str | None = None

    # 业务字段（与 ORM 完全同名；query_latest_regulations 消费面）
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    status: str | None = None
    source: str | None = None
    publish_date: date | None = None
    implementation_date: date | None = None
    notes: str | None = None
    article_no: str | None = None

    # 直读专有键：入库日期（created_at 的直读等价键）+ 两表归因
    input_date: date | None = None
    source_kind: str = ""  # collection | collection_env

    # 审计列（镜像有值；直读恒 None——PG 审计时间，spec D4）
    created_at: datetime | None = None
    updated_at: datetime | None = None


def view_from_record(
    record_id: str, kind: str, fields: dict[str, Any],
) -> KnowledgeArticleView:
    """Bitable 原始 fields dict → 视图对象（映射复用 handler 同一纯函数）。"""
    mapped = _map_knowledge_fields(fields) or {}
    view = KnowledgeArticleView(id=record_id, source_kind=kind)
    for key, value in mapped.items():
        setattr(view, key, value)
    view.feishu_record_id = record_id
    # article_no：handler 回写目标列（不在 KNOWLEDGE_BITABLE_TO_MODEL 内），
    # 探针实证两表暂无此列 → 恒 None；建列后文本/富文本两形态都归一
    raw_no = _extract_rich_text(fields.get("article_no")).strip()
    view.article_no = raw_no or None
    view.input_date = _ms_to_date(fields.get("入库日期"))
    return view
