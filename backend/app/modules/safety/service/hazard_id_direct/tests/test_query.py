"""hazard_id 直读查询单测（Ticket 04）——过滤/排序/分页 quirk/total/输出形态/
部门批量派生。"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.hazard_id_direct.query import (
    hazard_identifications,
    resolve_departments,
)
from app.modules.safety.service.hazard_id_direct.views import (
    HazardIdentificationView,
)

# legacy 输出键集（read_tools.items 逐字对齐）
HI_KEYS = {
    "hazard_id_no", "department", "position", "production_step",
    "specific_activity", "hazard_type", "possible_accident",
    "inherent_risk_label", "residual_risk_label", "post_risk_label",
    "control_level", "recommendation_content", "overall_status",
    "submitter_name", "feishu_url",
}


def _view(rid: str, **kw: Any) -> HazardIdentificationView:
    defaults: dict[str, Any] = dict(
        hazard_id_no=f"HI-{rid[-12:]}",
        position="结晶岗位",
        specific_activity="料液准备与过滤",
        hazard_type="火灾爆炸、机械伤害",
        possible_accident="爆炸",
        inherent_risk_label="一级/重大风险",
        residual_risk_label="三级/一般风险",
        post_risk_label="四级/低风险",
        control_level="公司级",
        recommendation_content="加装联锁",
        overall_status="completed",
        submitter_name="李伟豪",
        created_time_ms=1776300000000,
    )
    defaults.update(kw)
    return HazardIdentificationView(record_id=rid, **defaults)


class TestFilters:
    async def test_no_filter_returns_all_desc(self) -> None:
        views = [
            _view("recA", created_time_ms=100),
            _view("recB", created_time_ms=300),
            _view("recC", created_time_ms=200),
        ]
        items, total = hazard_identifications(views)
        assert total == 3
        assert [i["hazard_id_no"] for i in items] == [
            "HI-" + r[-12:] for r in ("recB", "recC", "recA")
        ]
        assert items[0]["specific_activity"] == "料液准备与过滤"

    async def test_department_filter_uses_identity_map(self) -> None:
        views = [
            _view("recA", submitter_name="李伟豪"),
            _view("recB", submitter_name="无名氏"),
        ]
        departments: dict[str, str | None] = {"李伟豪": "提炼工程五部"}
        items, total = hazard_identifications(
            views, departments=departments, department="提炼",
        )
        assert total == 1
        assert items[0]["hazard_id_no"] == "HI-" + "recA"[-12:]
        assert items[0]["department"] == "提炼工程五部"

    async def test_department_filter_no_match(self) -> None:
        views = [_view("recA", submitter_name="无名氏")]
        items, total = hazard_identifications(
            views, departments={}, department="提炼五部",
        )
        assert total == 0 and items == []

    async def test_position_filter(self) -> None:
        views = [_view("recA", position="合成"), _view("recB", position="结晶")]
        _, total = hazard_identifications(views, position="结晶")
        assert total == 1

    async def test_risk_stage_level_filter(self) -> None:
        views = [
            _view("recA", inherent_risk_label="一级/重大风险"),
            _view("recB", inherent_risk_label="三级/一般风险"),
        ]
        _, total = hazard_identifications(
            views, risk_stage="inherent", risk_level="重大",
        )
        assert total == 1
        _, total2 = hazard_identifications(
            views, risk_stage="residual", risk_level="3",
        )
        assert total2 == 2  # residual 全为 三级/一般 → 命中关键词「一般」

    async def test_risk_filter_silent_when_stage_unknown(self) -> None:
        """legacy quirk：stage/level 任一不可识别 → 静默不加条件。"""
        views = [_view("recA"), _view("recB")]
        _, total = hazard_identifications(
            views, risk_stage="bogus_stage", risk_level="一级",
        )
        assert total == 2
        _, total2 = hazard_identifications(
            views, risk_stage="inherent", risk_level="五级",
        )
        assert total2 == 2

    async def test_risk_level_alone_not_applied(self) -> None:
        """legacy：level 单独给（无 stage）不加条件。"""
        views = [_view("recA")]
        _, total = hazard_identifications(views, risk_level="一级")
        assert total == 1

    async def test_overall_status_exact_ci(self) -> None:
        views = [
            _view("recA", overall_status="completed"),
            _view("recB", overall_status="draft"),
        ]
        _, total = hazard_identifications(views, overall_status="COMPLETED")
        assert total == 1
        _, total2 = hazard_identifications(views, overall_status="draft")
        assert total2 == 1

    async def test_keyword_across_three_fields(self) -> None:
        views = [
            _view("recA", specific_activity="料液准备"),
            _view("recB", hazard_type="中毒窒息"),
            _view("recC", possible_accident="窒息"),
            _view("recD", position="窒息式岗位"),  # position 不在 keyword 三列内
        ]
        _, total = hazard_identifications(views, keyword="窒息")
        assert total == 2  # recB（hazard_type）/ recC（possible_accident）命中；
        # recA 三列均不含关键词、recD 只 position 含（不参与 keyword 三列）


class TestSortAndPagination:
    async def test_order_created_time_desc_nulls_last(self) -> None:
        views = [
            _view("recOld", created_time_ms=100),
            _view("recNull", created_time_ms=None),
            _view("recNew", created_time_ms=999),
        ]
        items, _ = hazard_identifications(views, page_size=10)
        assert [i["hazard_id_no"] for i in items] == [
            "HI-" + r[-12:] for r in ("recNew", "recOld", "recNull")
        ]

    async def test_pagination_offset_raw_page_size_limit_capped(self) -> None:
        """legacy quirk：offset 步进 raw page_size=150，limit cap=100。"""
        views = [
            _view(f"rec{i:03d}", created_time_ms=1000 - i) for i in range(150)
        ]
        # page1: offset 0 limit 100 → 前 100 行
        items1, total = hazard_identifications(views, page=1, page_size=150)
        assert total == 150 and len(items1) == 100
        # page2: offset 150（raw）→ 只剩 0 行（150-100=50 行被跳过）
        items2, _ = hazard_identifications(views, page=2, page_size=150)
        assert items2 == []

    async def test_page_clamped_to_one(self) -> None:
        views = [_view("recA")]
        items, _ = hazard_identifications(views, page=0, page_size=20)
        assert len(items) == 1

    async def test_total_is_filtered_count_not_page(self) -> None:
        views = [_view(f"rec{i:02d}") for i in range(30)]
        items, total = hazard_identifications(views, page=1, page_size=10)
        assert len(items) == 10 and total == 30


class TestOutputShape:
    async def test_item_keys_exactly_legacy(self) -> None:
        items, _ = hazard_identifications(
            [_view("recA")], departments={"李伟豪": "提炼工程五部"},
        )
        assert set(items[0]) == HI_KEYS
        assert items[0]["feishu_url"] is None  # 死值 quirk 复刻
        assert items[0]["department"] == "提炼工程五部"
        assert items[0]["hazard_id_no"] == "HI-" + "recA"[-12:]


class FakeResult:
    def __init__(self, rows: list[tuple[str, str | None]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str | None]]:
        return self._rows


class FakeDB:
    def __init__(self, rows: list[tuple[str, str | None]]) -> None:
        self._rows = rows
        self.executed = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed += 1
        return FakeResult(self._rows)


class TestResolveDepartments:
    async def test_batch_resolve_first_row_wins(self) -> None:
        db = FakeDB([
            ("李伟豪", "提炼工程五部"),
            ("李伟豪", "提炼工程六部"),  # 同名第二行：首条胜（handler .first 同语义）
            ("林锴彬", None),
        ])
        got = await resolve_departments(db, ["李伟豪", "林锴彬", "无名氏", None, " "])
        assert got == {"李伟豪": "提炼工程五部", "林锴彬": None}
        assert db.executed == 1

    async def test_empty_names_no_query(self) -> None:
        db = FakeDB([])
        got = await resolve_departments(db, [None, " ", ""])
        assert got == {} and db.executed == 0
