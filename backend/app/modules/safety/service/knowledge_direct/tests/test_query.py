"""knowledge 直读清单查询单测（Ticket 03）。

覆盖：cutoff 过滤、input_date desc 排序、**先截断 limit 再过滤** quirk、
impact_level 解析、business_domain 恒空 quirk（既有缺陷忠实复刻）、
输出键与 legacy query_latest_regulations 完全一致。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.modules.safety.service.knowledge_direct.query import latest_regulations
from app.modules.safety.service.knowledge_direct.views import KnowledgeArticleView

OUTPUT_KEYS = {
    "id", "article_no", "title", "category", "impact_level",
    "publish_date", "status", "source",
}


def _view(
    vid: str,
    *,
    input_date: date | None,
    notes: str | None = None,
    category: str | None = "laws_regulations",
    title: str | None = None,
    article_no: str | None = "LAW-X",
    publish_date: date | None = None,
    status: str | None = "published",
    source: str | None = "应急管理部",
) -> KnowledgeArticleView:
    return KnowledgeArticleView(
        id=vid, feishu_record_id=vid, input_date=input_date, notes=notes,
        category=category, title=title or f"标题{vid}", article_no=article_no,
        publish_date=publish_date, status=status, source=source,
    )


def _recent(days_ago: int) -> date:
    return date.today() - timedelta(days=days_ago)


def _sample() -> list[KnowledgeArticleView]:
    return [
        _view("rec_old", input_date=_recent(60)),  # 超出 30 天窗口
        _view("rec_a", input_date=_recent(1), notes="影响等级: 高"),
        _view("rec_b", input_date=_recent(5), notes="文号: X | 影响等级: 中"),
        _view("rec_c", input_date=_recent(10)),  # 无影响等级
        _view("rec_d", input_date=None),  # 入库日期缺失
        _view("rec_std", input_date=_recent(2), category="standards",
              notes="影响等级: 低"),
    ]


class TestCutoffAndSort:
    def test_cutoff_filters_old_and_null(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        ids = [i["id"] for i in got["items"]]
        assert "rec_old" not in ids
        assert "rec_d" not in ids
        assert {"rec_a", "rec_b", "rec_c", "rec_std"} <= set(ids)

    def test_sort_input_date_desc(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        dates = {
            "rec_a": _recent(1), "rec_std": _recent(2),
            "rec_b": _recent(5), "rec_c": _recent(10),
        }
        ranked = sorted(dates, key=lambda k: dates[k])  # 旧→新
        ids = [i["id"] for i in got["items"] if i["id"] in dates]
        assert ids == list(reversed(ranked))

    def test_days_window_extension(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=90)
        ids = [i["id"] for i in got["items"]]
        assert "rec_old" in ids  # 60 天前行进入 90 天窗口
        assert "rec_d" not in ids  # 空入库日期永不入选


class TestLegacyQuirks:
    def test_limit_truncates_before_impact_filter(self) -> None:
        """legacy SQL LIMIT 在前、Python 过滤在后 → 过滤后可少于 limit。

        排序后前 2 条 = rec_a(高)/rec_std(低)；impact_level=高 过滤掉 rec_std，
        第 3 条 rec_c（无标注，同样不符）不会被补位——恒 1 条。
        """
        got = latest_regulations(_sample(), limit=2, days=30, impact_level="高")
        assert [i["id"] for i in got["items"]] == ["rec_a"]
        assert got["total"] == 1

    def test_impact_level_parse_and_filter(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30, impact_level="中")
        assert [i["id"] for i in got["items"]] == ["rec_b"]

    def test_impact_level_none_when_unmarked(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        by_id = {i["id"]: i for i in got["items"]}
        assert by_id["rec_c"]["impact_level"] is None
        assert by_id["rec_a"]["impact_level"] == "高"

    def test_business_domain_filter_always_empty(self) -> None:
        """忠实复刻 legacy `business_domain not in category`：中文领域名对
        英文枚举 category 永不命中 → 传参恒空（既有缺陷不修，spec D5）。"""
        got = latest_regulations(
            _sample(), limit=100, days=30, business_domain="安全生产",
        )
        assert got["items"] == []
        assert got["total"] == 0

    def test_total_equals_items_len(self) -> None:
        got = latest_regulations(_sample(), limit=2, days=30)
        assert got["total"] == len(got["items"]) == 2


class TestOutputShape:
    def test_output_keys_match_legacy(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        for item in got["items"]:
            assert set(item) == OUTPUT_KEYS

    def test_item_values(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        by_id = {i["id"]: i for i in got["items"]}
        a = by_id["rec_a"]
        assert a["article_no"] == "LAW-X"
        assert a["title"] == "标题rec_a"
        assert a["category"] == "laws_regulations"
        assert a["status"] == "published"
        assert a["source"] == "应急管理部"

    def test_publish_date_none_serializes_null(self) -> None:
        got = latest_regulations(_sample(), limit=100, days=30)
        by_id = {i["id"]: i for i in got["items"]}
        assert by_id["rec_a"]["publish_date"] is None

    def test_publish_date_iso_format(self) -> None:
        d = _recent(3)
        views = [_view("rec_p", input_date=_recent(1), publish_date=d)]
        got = latest_regulations(views, limit=10, days=30)
        assert got["items"][0]["publish_date"] == d.isoformat()

    def test_empty_views(self) -> None:
        got = latest_regulations([], limit=10, days=30)
        assert got == {"items": [], "total": 0}
