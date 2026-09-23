"""knowledge 直读视图对象单测（Ticket 01）。

覆盖：视图字段契约固化、_map_knowledge_fields 复用映射（枚举/日期/富文本与
handler 同口径）、article_no 列缺失优雅降级（探针实证两表无此列）、
input_date（入库日期）解析、created_at/updated_at 恒 None。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.knowledge_direct.views import (
    KnowledgeArticleView,
    view_from_record,
)

# 探针实测时间戳样本（survey_knowledge.py 2026-09-23）
_PUBLISH_MS = 1745510400000
_IMPL_MS = 1761926400000
_INPUT_MS = 1782921600000


def _expected_date(ms: int) -> Any:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def _fields() -> dict[str, Any]:
    return {
        "法律法规及标准名称": [{"text": "中华人民共和国安全生产法", "type": "text"}],
        "法规类别": "安全类",
        "颁布机关": [{"text": "全国人大常委会", "type": "text"}],
        "颁布修订日期": _PUBLISH_MS,
        "实施日期": _IMPL_MS,
        "法规状态": "现行有效",
        "核心要点总结": [{"text": "安全生产领域基础性法律", "type": "text"}],
        "备注": [{"text": "文号: 主席令第88号 | 影响等级: 高", "type": "text"}],
        "article_no": [{"text": "LAW-20260425-001", "type": "text"}],
        "入库日期": _INPUT_MS,
    }


class TestFieldContract:
    def test_view_fields_fixed_set(self) -> None:
        """视图字段契约固化：ORM 同名子集 + 直读专有键 + 审计列。"""
        expected = {
            # 标识
            "id", "feishu_record_id",
            # ORM 业务列同名（query_latest_regulations 消费面）
            "title", "summary", "category", "status", "source",
            "publish_date", "implementation_date", "notes", "article_no",
            # 直读专有键
            "input_date", "source_kind",
            # 审计列（恒 None）
            "created_at", "updated_at",
        }
        assert set(KnowledgeArticleView.__dataclass_fields__) == expected


class TestMapping:
    def test_mapping_reuses_handler_semantics(self) -> None:
        view = view_from_record("rec1", "collection", _fields())
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.source_kind == "collection"
        assert view.title == "中华人民共和国安全生产法"
        # 枚举映射与 handler CATEGORY_CN_TO_EN 同口径
        assert view.category == "laws_regulations"
        assert view.source == "全国人大常委会"
        assert view.status == "published"  # 现行有效 → published
        assert view.summary == "安全生产领域基础性法律"
        assert view.notes == "文号: 主席令第88号 | 影响等级: 高"
        # 日期 ms → date（与 handler _ms_to_date 同口径，UTC 切日）
        assert view.publish_date == _expected_date(_PUBLISH_MS)
        assert view.implementation_date == _expected_date(_IMPL_MS)
        assert view.input_date == _expected_date(_INPUT_MS)

    def test_dirty_enum_values_use_handler_map(self) -> None:
        """脏枚举值照 handler 映射（不做容错）。"""
        fields = {
            "法律法规及标准名称": [{"text": "某标准", "type": "text"}],
            "法规类别": "二职业健康类",
            "法规状态": "现行有效(新)",
        }
        view = view_from_record("rec2", "collection_env", fields)
        assert view.category == "laws_regulations"
        assert view.status == "published"
        assert view.source_kind == "collection_env"

    def test_unknown_enum_falls_back_like_handler(self) -> None:
        fields = {
            "法律法规及标准名称": [{"text": "某标准", "type": "text"}],
            "法规类别": "未知类别",
            "法规状态": "未知状态",
        }
        view = view_from_record("rec3", "collection", fields)
        assert view.category == "other"  # handler get(val, "other")
        assert view.status == "draft"  # handler get(val, "draft")


class TestArticleNo:
    def test_article_no_missing_column_none(self) -> None:
        """探针实证两表无 article_no 列 → 直读优雅降级 None（D3）。"""
        fields = _fields()
        del fields["article_no"]
        view = view_from_record("rec1", "collection", fields)
        assert view.article_no is None

    def test_article_no_plain_str(self) -> None:
        """建列后 handler 回写纯字符串形态。"""
        fields = _fields()
        fields["article_no"] = "LAW-20260425-002"
        view = view_from_record("rec1", "collection", fields)
        assert view.article_no == "LAW-20260425-002"


class TestControlledNone:
    def test_audit_columns_none(self) -> None:
        """PG 审计时间不可直读 → created_at/updated_at 恒 None（spec D4）。"""
        view = view_from_record("rec1", "collection", _fields())
        assert view.created_at is None
        assert view.updated_at is None

    def test_empty_fields_minimal_view(self) -> None:
        view = view_from_record("rec9", "collection", {})
        assert view.id == "rec9"
        assert view.title is None
        assert view.input_date is None
        assert view.article_no is None
