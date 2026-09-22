"""emergency_drill 直读查询/统计单测（Ticket 02）。

覆盖：filter_views 全分支（精确/keyword/stage 三态）、sort_views（D3 默认排序
NULLS LAST）、paginate、stats_of（含「未分类」分组）。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.emergency_drill_direct.query import (
    filter_views,
    find_view,
    paginate,
    sort_views,
    stats_of,
)
from app.modules.safety.service.emergency_drill_direct.views import (
    EmergencyDrillRecordView,
)


def _view(vid: str, **kw: object) -> EmergencyDrillRecordView:
    return EmergencyDrillRecordView(id=vid, feishu_record_id=vid, **kw)  # type: ignore[arg-type]


def _sample() -> list[EmergencyDrillRecordView]:
    return [
        _view("rec1", department="设备动力部", drill_type="应急疏散演练",
              status=None, drill_content="第一季度火灾疏散演练",
              execution_time=date(2026, 1, 20), plan_time_ref=date(2026, 1, 5)),
        _view("rec2", department="设备动力部", drill_type="现场岗位处置",
              status="已完成", drill_content="危废库泄漏处置演练",
              execution_time=date(2026, 2, 10), plan_time_ref=date(2026, 2, 1)),
        _view("rec3", department="安全环保部", drill_type="应急疏散演练",
              status="未完成", drill_content="宿舍楼疏散演练",
              execution_time=None, plan_time_ref=None),
        _view("rec4", department=None, drill_type=None,
              status=None, drill_content=None,
              execution_time=None, plan_time_ref=date(2025, 12, 30)),
    ]


class TestFilterViews:
    def test_no_filters_returns_all(self) -> None:
        views = _sample()
        assert filter_views(views) == views

    def test_exact_filters(self) -> None:
        views = _sample()
        assert [v.id for v in filter_views(views, department="设备动力部")] == [
            "rec1", "rec2",
        ]
        assert [v.id for v in filter_views(views, drill_type="应急疏散演练")] == [
            "rec1", "rec3",
        ]
        assert [v.id for v in filter_views(views, status="已完成")] == ["rec2"]

    def test_keyword_ci_substring(self) -> None:
        views = _sample()
        assert [v.id for v in filter_views(views, keyword="疏散")] == [
            "rec1", "rec3",
        ]
        assert [v.id for v in filter_views(views, keyword="泄漏处置")] == ["rec2"]
        # 空字段不参与命中
        assert filter_views(views, keyword="当班") == []

    def test_stage_three_states(self) -> None:
        views = _sample()
        assert [v.id for v in filter_views(views, stage="plan")] == ["rec3", "rec4"]
        assert [v.id for v in filter_views(views, stage="execution")] == [
            "rec1", "rec2",
        ]
        assert [v.id for v in filter_views(views, stage="review")] == [
            "rec2", "rec3",
        ]

    def test_combined_filters(self) -> None:
        views = _sample()
        got = filter_views(views, department="设备动力部", stage="plan")
        assert got == []


class TestSortViews:
    def test_default_plan_time_ref_desc_nulls_last(self) -> None:
        ordered = sort_views(_sample())
        assert [v.id for v in ordered] == ["rec2", "rec1", "rec4", "rec3"]

    def test_stable_within_equal_keys(self) -> None:
        views = [
            _view("recA", plan_time_ref=date(2026, 1, 1)),
            _view("recB", plan_time_ref=date(2026, 1, 1)),
            _view("recC", plan_time_ref=None),
        ]
        ordered = sort_views(views)
        assert [v.id for v in ordered] == ["recA", "recB", "recC"]


class TestPaginate:
    def test_pages_and_total(self) -> None:
        views = _sample()
        page1, total = paginate(views, 0, 2)
        assert total == 4
        assert [v.id for v in page1] == ["rec1", "rec2"]
        page2, total2 = paginate(views, 2, 2)
        assert total2 == 4
        assert [v.id for v in page2] == ["rec3", "rec4"]
        page3, _ = paginate(views, 4, 2)
        assert page3 == []


class TestStatsOf:
    def test_stats_matches_legacy_semantics(self) -> None:
        stats = stats_of(_sample())
        assert stats["total"] == 4
        assert stats["executed"] == 2
        assert stats["completed"] == 1
        assert stats["pending"] == 3
        assert stats["by_type"] == {
            "应急疏散演练": 2, "现场岗位处置": 1, "未分类": 1,
        }
        assert stats["by_department"] == {
            "设备动力部": 2, "安全环保部": 1, "未分类": 1,
        }

    def test_stats_empty(self) -> None:
        stats = stats_of([])
        assert stats == {
            "total": 0, "executed": 0, "completed": 0, "pending": 0,
            "by_type": {}, "by_department": {},
        }


class TestFindView:
    def test_find_by_rec_id(self) -> None:
        views = _sample()
        assert find_view(views, "rec3") is views[2]
        assert find_view(views, "recZZZ") is None
