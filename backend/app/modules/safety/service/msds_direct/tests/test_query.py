"""msds 直读侧台账查询单测（Ticket 02）——legacy list_documents 语义复刻。"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.msds_direct.query import msds_documents
from app.modules.safety.service.msds_direct.views import MsdsDocumentView

# legacy 工具体输出键（read_tools.query_msds_documents 逐字对齐）
LEGACY_ITEM_KEYS = {
    "id", "name", "cas_no", "molecular_formula", "un_no",
    "hazard_statement", "appearance", "flash_point", "relative_density",
    "pc_twa", "health_hazard", "first_aid", "review_status", "archive_status",
}


def _view(vid: str, *, name: str | None = None, cas: str | None = None,
          d: date | None = None) -> MsdsDocumentView:
    return MsdsDocumentView(id=vid, feishu_record_id=vid, name=name,
                            cas_no=cas, source_date=d)


class TestFilters:
    async def test_name_contains_case_insensitive(self) -> None:
        views = [_view("1", name="Isopropanol IP"), _view("2", name="异丙醇")]
        items, total = msds_documents(views, name="PROPANOL")
        assert total == 1
        assert items[0]["id"] == "1"

    async def test_cas_no_contains(self) -> None:
        views = [_view("1", cas="67-63-0"), _view("2", cas="67-68-5")]
        items, total = msds_documents(views, cas_no="67-6")
        assert total == 2
        assert {i["id"] for i in items} == {"1", "2"}

    async def test_name_and_cas_combined(self) -> None:
        views = [
            _view("1", name="异丙醇", cas="67-63-0"),
            _view("2", name="异丙醇", cas="67-68-5"),
            _view("3", name="二甲基亚砜", cas="67-68-5"),
        ]
        items, total = msds_documents(views, name="异丙醇", cas_no="67-68-5")
        assert total == 1
        assert items[0]["id"] == "2"

    async def test_no_filter_returns_all(self) -> None:
        views = [_view("1"), _view("2"), _view("3")]
        items, total = msds_documents(views)
        assert total == 3
        assert len(items) == 3


class TestSortPagination:
    async def test_source_date_desc_nulls_last(self) -> None:
        views = [
            _view("none1", d=None),
            _view("d2", d=date(2026, 8, 6)),
            _view("d1", d=date(2026, 8, 5)),
            _view("none2", d=None),
        ]
        items, total = msds_documents(views)
        assert [i["id"] for i in items] == ["d2", "d1", "none1", "none2"]
        assert total == 4

    async def test_skip_limit_and_total(self) -> None:
        views = [_view(str(i), d=date(2026, 8, i + 1)) for i in range(5)]
        items, total = msds_documents(views, limit=2, skip=1)
        # 排序后第 2、3 条（desc：08-05、08-04）
        assert [i["id"] for i in items] == ["3", "2"]
        assert total == 5  # total 为过滤后全量计数，非页大小


class TestOutputContract:
    async def test_item_keys_match_legacy_tool(self) -> None:
        views = [_view("1", name="异丙醇", cas="67-63-0", d=date(2026, 8, 6))]
        items, _ = msds_documents(views)
        assert set(items[0].keys()) == LEGACY_ITEM_KEYS
        assert items[0]["review_status"] == "pending"
        assert items[0]["archive_status"] == "pending"
        assert items[0]["name"] == "异丙醇"

    async def test_none_fields_pass_through(self) -> None:
        items, _ = msds_documents([_view("1")])
        assert items[0]["name"] is None
        assert items[0]["cas_no"] is None
