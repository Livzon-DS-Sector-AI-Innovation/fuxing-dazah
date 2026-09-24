"""ehs_change 直读侧查询单测（Ticket 03）——六筛选/排序/分页 quirk/输出键集。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.ehs_change_direct.query import ehs_changes
from app.modules.safety.service.ehs_change_direct.views import EhsChangeView


def _view(rid: str, **kw: Any) -> EhsChangeView:
    defaults: dict[str, Any] = dict(
        kind="approval",
        created_time_ms=1776300000000,
        change_no=f"BT-{rid}",
        title=f"变更{rid}",
        change_type="equipment_facility",
        change_grade="major",
        department="精制工程一部",
        status="approved",
        description=None,
        expected_start=None,
        applicant_name="赵军元",
        ai_review_status="completed",
    )
    defaults.update(kw)
    return EhsChangeView(record_id=rid, **defaults)


def _iso_keys(item: dict[str, Any]) -> set[str]:
    return set(item)


class TestFilters:
    def test_no_filter_returns_all_sorted_desc(self) -> None:
        views = [_view("recA", created_time_ms=100), _view("recB", created_time_ms=300),
                 _view("recC", created_time_ms=200)]
        items, total = ehs_changes(views)
        assert total == 3
        assert [i["change_no"] for i in items] == ["BT-recB", "BT-recC", "BT-recA"]

    def test_department_contains(self) -> None:
        views = [_view("recA", department="精制工程一部"),
                 _view("recB", department="提炼工程五部")]
        items, total = ehs_changes(views, department="精制")
        assert total == 1
        assert items[0]["change_no"] == "BT-recA"

    def test_change_type_exact_stripped(self) -> None:
        views = [_view("recA", change_type="equipment_facility"),
                 _view("recB", change_type="process_tech")]
        _, total = ehs_changes(views, change_type=" process_tech ")
        assert total == 1

    def test_change_grade_norm(self) -> None:
        views = [_view("recA", change_grade="major"),
                 _view("recB", change_grade="general")]
        # 中文标签 → code
        _, t1 = ehs_changes(views, change_grade="重大")
        # 小写 code 兼容
        _, t2 = ehs_changes(views, change_grade="MAJOR")
        # 未知值原样返回 = 零命中（legacy 同款）
        _, t3 = ehs_changes(views, change_grade="特大")
        assert (t1, t2, t3) == (1, 1, 0)

    def test_status_lower(self) -> None:
        views = [_view("recA", status="approved"),
                 _view("recB", status="under_review")]
        items, total = ehs_changes(views, status="Approved")
        assert total == 1
        assert items[0]["change_no"] == "BT-recA"

    def test_ai_review_status_lower(self) -> None:
        views = [_view("recA", ai_review_status="completed"),
                 _view("recB", ai_review_status="none")]
        _, total = ehs_changes(views, ai_review_status="None")
        assert total == 1

    def test_keyword_title_or_description(self) -> None:
        views = [
            _view("recA", title="溶剂回收塔改造"),
            _view("recB", title="其他", description="涉及溶剂更换"),
            _view("recC", title="无关", description=None),
        ]
        _, total = ehs_changes(views, keyword="溶剂")
        assert total == 2

    def test_combined_filters(self) -> None:
        views = [
            _view("recA", department="精制工程一部", change_grade="major"),
            _view("recB", department="精制工程一部", change_grade="general"),
            _view("recC", department="提炼工程五部", change_grade="major"),
        ]
        _, total = ehs_changes(views, department="精制", change_grade="重大")
        assert total == 1


class TestSortAndPagination:
    def test_missing_created_time_goes_last(self) -> None:
        views = [
            _view("recA", created_time_ms=None),
            _view("recB", created_time_ms=100),
        ]
        items, _ = ehs_changes(views)
        assert [i["change_no"] for i in items] == ["BT-recB", "BT-recA"]

    def test_page_offset_raw_and_limit_cap(self) -> None:
        views = [
            _view(f"rec{i:02d}", created_time_ms=1000 - i) for i in range(12)
        ]
        # legacy quirk：offset 步进用 raw page_size（5），limit 取 min(5,100)
        items, total = ehs_changes(views, page=2, page_size=5)
        assert total == 12
        assert [i["change_no"] for i in items] == [
            "BT-rec05", "BT-rec06", "BT-rec07", "BT-rec08", "BT-rec09",
        ]

    def test_limit_capped_at_100(self) -> None:
        views = [_view(f"rec{i:03d}", created_time_ms=i) for i in range(120)]
        items, total = ehs_changes(views, page=1, page_size=150)
        assert total == 120
        assert len(items) == 100  # cap 只作用 limit

    def test_page_floor_at_1(self) -> None:
        views = [_view("recA")]
        items, total = ehs_changes(views, page=0, page_size=20)
        assert total == 1
        assert items[0]["change_no"] == "BT-recA"


class TestOutputShape:
    EHS_KEYS = {
        "change_no", "title", "change_type", "change_grade", "department",
        "location_unit", "status", "expected_start", "expected_completion",
        "actual_start", "actual_completion", "applicant_name",
        "ai_review_status",
    }

    def test_item_keys_and_isoformat(self) -> None:
        dt = datetime(2025, 12, 2, 16, 0, tzinfo=UTC)
        views = [_view("recA", expected_start=dt)]
        items, _ = ehs_changes(views)
        assert _iso_keys(items[0]) == self.EHS_KEYS
        assert items[0]["expected_start"] == dt.isoformat()
        # 恒 None 复刻（状态机零使用）
        assert items[0]["actual_start"] is None
        assert items[0]["actual_completion"] is None
        assert items[0]["expected_completion"] is None
        assert items[0]["location_unit"] is None

    def test_empty_views(self) -> None:
        items, total = ehs_changes([])
        assert items == [] and total == 0
