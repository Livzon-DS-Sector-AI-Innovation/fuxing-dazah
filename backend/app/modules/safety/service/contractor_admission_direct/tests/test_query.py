"""contractor_admission 直读查询/统计单测（Ticket 03）。

覆盖：过滤全分支（含派生 AI 态过滤、processing/failed 恒空）、
Postgres NULLS 排序口径（ASC LAST / DESC FIRST）、内存分页、stats 三分组。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.safety.service.contractor_admission_direct.query import (
    filter_views,
    find_view,
    paginate,
    sort_views,
    stats_of,
)
from app.modules.safety.service.contractor_admission_direct.views import (
    ContractorAdmissionView,
    view_from_record_id,
)


def _view(
    vid: str,
    *,
    company: str | None = None,
    party: str | None = None,
    submit: str | None = None,
    ai_status: str = "none",
    conclusion: str | None = None,
    entry: date | None = None,
    created: datetime | None = None,
    contact: str | None = None,
) -> ContractorAdmissionView:
    result = None
    if ai_status == "completed":
        result = {
            "agreement": None, "license": None, "insurance": None,
            "overall_conclusion": conclusion,
            "overall_report": "", "defect_categories": [], "regulations": [],
        }
    return ContractorAdmissionView(
        id=vid,
        feishu_record_id=vid,
        feishu_table_id="admission",
        company_name=company,
        related_party_type=party,
        submit_status=submit,
        contact_person=contact,
        ai_review_status=ai_status,
        ai_review_result=result,
        entry_date=entry,
        created_at=created,
    )


def _views() -> list[ContractorAdmissionView]:
    return [
        _view("r1", company="甲公司", party="承包商", submit="已完成",
              ai_status="completed", conclusion="审核通过",
              entry=date(2026, 1, 10), created=datetime(2026, 1, 1, tzinfo=UTC)),
        _view("r2", company="乙公司", party="合作类相关方", submit="进行中",
              ai_status="none", entry=date(2026, 2, 1),
              created=datetime(2026, 2, 1, tzinfo=UTC), contact="张三"),
        _view("r3", company=None, party=None, submit=None,
              ai_status="none", entry=None, created=None),
        _view("r4", company="丙公司", party="承包商", submit="已完成",
              ai_status="completed", conclusion="需补充完善",
              entry=date(2026, 3, 1), created=datetime(2026, 3, 1, tzinfo=UTC)),
    ]


class TestFilterViews:
    def test_exact_filters(self) -> None:
        views = _views()
        assert [v.id for v in filter_views(views, related_party_type="承包商")] == ["r1", "r4"]
        assert [v.id for v in filter_views(views, submit_status="已完成")] == ["r1", "r4"]
        assert [v.id for v in filter_views(views, ai_review_status="none")] == ["r2", "r3"]
        assert [v.id for v in filter_views(views, ai_review_status="completed")] == ["r1", "r4"]

    def test_ai_review_status_processing_failed_always_empty(self) -> None:
        """派生态只含 none/completed：processing/failed 过滤恒空（spec §4.2）。"""
        assert filter_views(_views(), ai_review_status="processing") == []
        assert filter_views(_views(), ai_review_status="failed") == []

    def test_ai_conclusion_exact(self) -> None:
        ids = [v.id for v in filter_views(_views(), ai_conclusion="需补充完善")]
        assert ids == ["r4"]

    def test_keyword_ci_two_fields(self) -> None:
        views = _views()
        assert [v.id for v in filter_views(views, keyword="乙")] == ["r2"]
        # 大小写不敏感复刻 ilike：对数据中的拉丁字符生效
        views_latin = [v for v in views if v.id == "r1"] + [
            _view("r5", company="ABC Corp"),
        ]
        assert [v.id for v in filter_views(views_latin, keyword="abc")] == ["r5"]
        assert [v.id for v in filter_views(views_latin, keyword="ABC")] == ["r5"]

    def test_combined(self) -> None:
        ids = [v.id for v in filter_views(
            _views(), related_party_type="承包商", ai_conclusion="审核通过",
        )]
        assert ids == ["r1"]


class TestSortViews:
    def test_default_created_at_desc_nulls_first(self) -> None:
        """默认 created_at desc，PG 口径 DESC NULLS FIRST。"""
        order = [v.id for v in sort_views(_views())]
        assert order == ["r3", "r4", "r2", "r1"]

    def test_created_at_asc_nulls_last(self) -> None:
        order = [v.id for v in sort_views(_views(), "created_at", "asc")]
        assert order == ["r1", "r2", "r4", "r3"]

    def test_entry_date_desc_nulls_first(self) -> None:
        order = [v.id for v in sort_views(_views(), "entry_date", "desc")]
        assert order[0] == "r3"
        assert order[1:] == ["r4", "r2", "r1"]

    def test_unknown_sort_by_falls_back_created_at(self) -> None:
        assert [v.id for v in sort_views(_views(), "hack")] == [
            v.id for v in sort_views(_views(), "created_at", "desc")
        ]

    def test_company_name_desc_nulls_first(self) -> None:
        order = [v.id for v in sort_views(_views(), "company_name", "desc")]
        assert order[0] == "r3"
        # 码点序：甲(U+7532) > 乙(U+4E59) > 丙(U+4E19)
        assert order[1:] == ["r1", "r2", "r4"]


class TestPaginateStats:
    def test_paginate(self) -> None:
        views = _views()
        page, total = paginate(views, skip=1, limit=2)
        assert total == 4
        assert [v.id for v in page] == [views[1].id, views[2].id]
        page, total = paginate(views, skip=10, limit=20)
        assert page == [] and total == 4

    def test_stats_groups_with_unknown(self) -> None:
        stats = stats_of(_views())
        assert stats["total"] == 4
        assert stats["by_ai_review_status"] == {"completed": 2, "none": 2}
        assert stats["by_related_party_type"] == {
            "承包商": 2, "合作类相关方": 1, "未知": 1,
        }
        assert stats["by_submit_status"] == {
            "已完成": 2, "进行中": 1, "未知": 1,
        }

    def test_find_view(self) -> None:
        views = _views()
        assert find_view(views, "r2") is views[1]
        assert find_view(views, "nope") is None


class TestViewFromRecordIdCompat:
    def test_view_validates_like_orm_row(self) -> None:
        """视图属性面与 ORM 行等价（API model_validate 兼容性的基础）。"""
        view = view_from_record_id("recX", {
            "作业单位名称": [{"text": "测试公司", "type": "text"}],
            "提交状态": "已完成",
            "AI审核结论": "审核通过",
        })
        for attr in ("id", "company_name", "submit_status", "ai_review_status",
                     "ai_review_result", "created_at", "entry_date"):
            assert hasattr(view, attr)
