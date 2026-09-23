"""oh 直读侧查询单测（Ticket 02）——过滤/NULLS LAST 排序/分页/legacy quirk 复刻。"""

from __future__ import annotations

from app.modules.safety.service.oh_direct.query import (
    oh_hazard_factors,
    oh_positions,
)
from app.modules.safety.service.oh_direct.views import (
    OhHazardFactorView,
    OhPositionView,
)

# legacy 工具体输出键（read_tools.query_oh_* 逐字对齐）
POSITION_KEYS = {
    "id", "department", "position", "job_title",
    "hazard_factors", "hazard_factors_status",
}
FACTOR_KEYS = {"id", "factor_name", "ppe_respiratory"}


def _pos(vid: str, *, dept: str | None = None, pos: str | None = None,
         factors: list[str] | None = None,
         status: str | None = None) -> OhPositionView:
    return OhPositionView(
        id=vid, feishu_record_id=vid,
        department=dept, position=pos,
        hazard_factors=factors,
        hazard_factors_status=status
        if status is not None
        else ("filled" if factors else "empty"),
    )


def _fac(vid: str, name: str, ppe: str | None = None) -> OhHazardFactorView:
    return OhHazardFactorView(id=vid, feishu_record_id=vid,
                              factor_name=name, ppe_respiratory=ppe)


class TestOhPositions:
    def test_department_filter(self) -> None:
        views = [_pos("1", dept="生产部"), _pos("2", dept="质检部")]
        items, total = oh_positions(views, department="生产部")
        assert total == 1
        assert items[0]["id"] == "1"

    def test_status_filter(self) -> None:
        views = [
            _pos("1", dept="生产部", factors=["噪声"]),
            _pos("2", dept="生产部"),
        ]
        items, total = oh_positions(views, hazard_factors_status="filled")
        assert total == 1
        assert items[0]["id"] == "1"

    def test_filters_combined(self) -> None:
        views = [
            _pos("1", dept="生产部", factors=["噪声"]),
            _pos("2", dept="生产部"),
            _pos("3", dept="质检部", factors=["噪声"]),
        ]
        items, total = oh_positions(
            views, department="生产部", hazard_factors_status="filled",
        )
        assert total == 1
        assert items[0]["id"] == "1"

    def test_no_filter_returns_all(self) -> None:
        views = [_pos("1", dept="生产部"), _pos("2", dept="质检部")]
        items, total = oh_positions(views)
        assert total == 2
        assert len(items) == 2

    def test_sort_nulls_last_then_position(self) -> None:
        views = [
            _pos("pos2", dept="生产部", pos="操作工"),
            _pos("deptB", dept="质检部", pos="检验员"),
            _pos("deptA", dept="生产部", pos="班长"),
            _pos("null_dept", dept=None, pos="检验员"),
        ]
        items, _ = oh_positions(views)
        # 码点序（受控偏差落档 spec D3）：生 U+751F < 质 U+8D28；
        # 生产部内 操 U+64CD < 班 U+73ED；department NULL 恒最后
        assert [i["id"] for i in items] == [
            "pos2", "deptA", "deptB", "null_dept",
        ]

    def test_sort_position_nulls_last_within_department(self) -> None:
        views = [
            _pos("has_pos", dept="生产部", pos="班长"),
            _pos("null_pos", dept="生产部", pos=None),
        ]
        items, _ = oh_positions(views)
        assert [i["id"] for i in items] == ["has_pos", "null_pos"]

    def test_pagination_and_total(self) -> None:
        views = [_pos(str(i), dept=f"部门{i}") for i in range(5)]
        items, total = oh_positions(views, skip=1, limit=2)
        assert [i["id"] for i in items] == ["1", "2"]
        assert total == 5  # total 为过滤后全量计数，非页大小

    def test_output_contract(self) -> None:
        views = [_pos("1", dept="生产部", pos="操作工", factors=["噪声"])]
        items, _ = oh_positions(views)
        assert set(items[0].keys()) == POSITION_KEYS
        assert items[0]["hazard_factors"] == ["噪声"]
        assert items[0]["hazard_factors_status"] == "filled"
        assert items[0]["job_title"] is None  # 死列（spec D6）

    def test_hazard_factors_none_projected_to_empty_list(self) -> None:
        items, _ = oh_positions([_pos("1", dept="生产部")])
        assert items[0]["hazard_factors"] == []


class TestOhHazardFactors:
    def test_no_keyword_total_is_window_size(self) -> None:
        # legacy quirk：无 keyword 时 total=min(limit, 全表数)（spec D5）
        views = [_fac(str(i), f"因素{i}") for i in range(10)]
        items, total = oh_hazard_factors(views, limit=3)
        assert len(items) == 3
        assert total == 3

    def test_sort_factor_name_asc(self) -> None:
        views = [_fac("3", "噪声"), _fac("1", "氨"), _fac("2", "苯")]
        items, _ = oh_hazard_factors(views, limit=50)
        # Python str 码点序（受控偏差落档 spec D3）：噪 U+566A < 氨 U+6C28 < 苯 U+82EF
        assert [i["factor_name"] for i in items] == ["噪声", "氨", "苯"]

    def test_keyword_filters_within_window(self) -> None:
        views = [_fac(str(i), n) for i, n in enumerate(
            ["噪声", "氨", "高温", "甲醇", "甲醛"], start=1,
        )]
        items, total = oh_hazard_factors(views, keyword="甲")
        assert [i["factor_name"] for i in items] == ["甲醇", "甲醛"]
        assert total == 2

    def test_quirk_keyword_miss_beyond_window_returns_empty(self) -> None:
        # legacy quirk 忠实复刻：先 LIMIT 截断再 keyword 过滤——匹配行若在
        # 窗口外则不返回（spec D5；sort 键升序下「苯」排在窗口 2 之外）
        views = [_fac("1", "氨"), _fac("2", "噪声"), _fac("3", "苯")]
        items, total = oh_hazard_factors(views, keyword="苯", limit=2)
        assert items == []
        assert total == 0

    def test_keyword_stripped(self) -> None:
        views = [_fac("1", "噪声")]
        items, total = oh_hazard_factors(views, keyword=" 噪 ")
        assert total == 1
        assert items[0]["id"] == "1"

    def test_output_contract(self) -> None:
        items, _ = oh_hazard_factors([_fac("1", "噪声", "耳塞")])
        assert set(items[0].keys()) == FACTOR_KEYS
        assert items[0]["ppe_respiratory"] == "耳塞"
