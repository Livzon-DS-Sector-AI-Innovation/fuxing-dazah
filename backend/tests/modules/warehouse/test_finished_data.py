"""成品数据读取层测试（V3.0 分期D Ticket 02，§4.5 成品③ / §4.8 ⑥）。

接缝：服务函数级 + FakeAdapter 注入（沿 test_base_mirror / test_push_center 模式）——
- 单元格解析（cell_date/cell_qty）与四态判定纯函数直测；
- 分页拉取/日聚合/质量分布走 FakeFinishedAdapter（含多页翻页）；
- 生成器 dry_run：monkeypatch bitable_adapter.WarehouseBitableAdapter 为
  FakeFinishedAdapter 工厂，断言卡片结构与关键数字。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.warehouse.finished_data import (
    STATE_INVOICED_SHIPPED,
    STATE_INVOICED_UNSHIPPED,
    STATE_SHIPPED_UNINVOICED,
    cell_date,
    cell_qty,
    classify_invoice_state,
    fetch_all_records,
    fetch_day_movements,
    fetch_month_finished_io,
    fetch_quality_distribution,
    month_bounds,
    summarize_invoice_states,
)
from app.modules.warehouse.push_center import generators

CN_TZ = ZoneInfo("Asia/Shanghai")

NOW = datetime(2026, 9, 21, 9, 0, tzinfo=CN_TZ)  # 周一


# ═══════════════════════════════════════════════════════════════
# 单元格解析
# ═══════════════════════════════════════════════════════════════


class TestCellDate:
    def test_ms_timestamp(self) -> None:
        # 1760457600000 = 2025-10-15 00:00 +08:00（探针样例）
        assert cell_date(1760457600000) == date(2025, 10, 15)

    def test_seconds_timestamp_upgraded(self) -> None:
        assert cell_date(1760457600) == date(2025, 10, 15)

    def test_iso_text(self) -> None:
        assert cell_date("2026-09-21") == date(2026, 9, 21)

    def test_slash_text(self) -> None:
        assert cell_date("2026/09/21") == date(2026, 9, 21)

    def test_formula_wrapped(self) -> None:
        assert cell_date({"type": 5, "value": [1760457600000]}) == date(2025, 10, 15)

    @pytest.mark.parametrize("value", [None, True, 0, -5, "", "abc", []])
    def test_empty_or_invalid(self, value: Any) -> None:
        assert cell_date(value) is None


class TestCellQty:
    def test_plain_number(self) -> None:
        assert cell_qty(12.5) == 12.5

    def test_wrapped_number(self) -> None:
        assert cell_qty({"type": 20, "value": [0.6]}) == 0.6

    def test_unit_text(self) -> None:
        assert cell_qty("0.6kg") == 0.6

    def test_thousand_separator_text(self) -> None:
        assert cell_qty("1,234.5十亿") == 1234.5

    def test_none_and_non_numeric(self) -> None:
        assert cell_qty(None) is None
        assert cell_qty("kg") is None
        assert cell_qty("") is None


# ═══════════════════════════════════════════════════════════════
# 四态判定与聚合
# ═══════════════════════════════════════════════════════════════


class TestClassifyInvoiceState:
    def test_matrix(self) -> None:
        assert classify_invoice_state(10.0, 5.0) == STATE_INVOICED_SHIPPED
        assert classify_invoice_state(10.0, None) == STATE_SHIPPED_UNINVOICED
        assert classify_invoice_state(10.0, 0.0) == STATE_SHIPPED_UNINVOICED
        assert classify_invoice_state(None, 5.0) == STATE_INVOICED_UNSHIPPED
        assert classify_invoice_state(0.0, 5.0) == STATE_INVOICED_UNSHIPPED
        assert classify_invoice_state(None, None) is None
        assert classify_invoice_state(0.0, 0.0) is None


def _sales_row(
    record_id: str,
    *,
    day: date | None = date(2026, 9, 10),
    customer: str = "Hikma Jordan",
    product: str = "达托霉素",
    shipped: float | None = 10.0,
    invoiced: float | None = None,
) -> Any:
    from app.modules.warehouse.finished_data import _parse_daily_sales_row

    return _parse_daily_sales_row(
        {
            "record_id": record_id,
            "fields": {
                "销售日期": int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp() * 1000)
                if day
                else None,
                "产品名称": product,
                "品规": "DT高规二期（AB线）",
                "销售客户": customer,
                "出库量-开票工作流使用": shipped,
                "开票数量": invoiced,
            },
        }
    )


class TestSummarizeInvoiceStates:
    def test_month_window_and_aggregation(self) -> None:
        rows = [
            _sales_row("a", shipped=10.0, invoiced=10.0),  # 本月 双有
            _sales_row("b", shipped=20.0, invoiced=None),  # 本月 发货未开票
            _sales_row("c", shipped=None, invoiced=5.0),  # 本月 开票未发货
            _sales_row("d", day=date(2026, 8, 31), shipped=99.0, invoiced=None),  # 上月不进窗
            _sales_row("e", day=None, shipped=1.0, invoiced=None),  # 无日期跳过
        ]
        start, end = month_bounds(2026, 9)
        summary = summarize_invoice_states(rows, month_start=start, month_end=end)
        assert summary.invoiced_shipped_count == 1
        assert summary.invoiced_shipped_qty == 10.0
        assert summary.shipped_uninvoiced_count == 1
        assert summary.shipped_uninvoiced_qty == 20.0
        assert summary.invoiced_unshipped_count == 1
        assert summary.invoiced_unshipped_qty == 5.0
        assert [r.record_id for r in summary.unbilled_detail] == ["b"]

    def test_unbilled_detail_sorted_by_qty_desc(self) -> None:
        rows = [
            _sales_row("small", shipped=1.0, invoiced=None),
            _sales_row("big", shipped=50.0, invoiced=None),
            _sales_row("mid", shipped=10.0, invoiced=None),
        ]
        start, end = month_bounds(2026, 9)
        summary = summarize_invoice_states(rows, month_start=start, month_end=end)
        assert [r.record_id for r in summary.unbilled_detail] == ["big", "mid", "small"]


# ═══════════════════════════════════════════════════════════════
# FakeAdapter：分页/聚合读取
# ═══════════════════════════════════════════════════════════════


class FakeFinishedAdapter:
    """records/search 桩：按 table_key 返回预设行，支持 token 翻页。"""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.calls: list[tuple[str, int]] = []

    async def search_records_page(
        self,
        table_key: str,
        filter_json: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        limit: int = 20,
        page_token: str | None = None,
        sort: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((table_key, int(page_token or 0)))
        rows = self.tables.get(table_key, [])
        start = int(page_token or 0)
        chunk = rows[start : start + limit]
        nxt = start + limit
        return {
            "records": chunk,
            "total": len(rows),
            "page_token": str(nxt) if nxt < len(rows) else None,
        }


def _receipt_row(
    record_id: str,
    *,
    day: date | None,
    qty: float = 5.0,
    status: str = "合格",
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "fields": {
            "入库日期": int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp() * 1000)
            if day
            else None,
            "产品名称": "达托霉素",
            "产品批号": "DA2609001",
            "入库数量": qty,
            "质量状态": status,
        },
    }


class TestFetchAllRecords:
    async def test_pagination_joins_pages(self) -> None:
        rows = [{"record_id": f"r{i}", "fields": {}} for i in range(501)]
        adapter = FakeFinishedAdapter({"finished_receipt": rows})
        out = await fetch_all_records(adapter, "finished_receipt", ["x"])
        assert len(out) == 501
        assert adapter.calls == [("finished_receipt", 0), ("finished_receipt", 500)]

    async def test_empty_table(self) -> None:
        adapter = FakeFinishedAdapter({})
        assert await fetch_all_records(adapter, "finished_receipt", ["x"]) == []


class TestFetchDayMovements:
    async def test_counts_only_target_day(self) -> None:
        adapter = FakeFinishedAdapter(
            {
                "finished_receipt": [
                    _receipt_row("in1", day=date(2026, 9, 20), qty=5.0),
                    _receipt_row("in2", day=date(2026, 9, 20), qty=7.0),
                    _receipt_row("old", day=date(2026, 9, 19), qty=99.0),
                ],
                "finished_outbound": [
                    {
                        "record_id": "out1",
                        "fields": {
                            "出库日期": int(
                                datetime(2026, 9, 20, tzinfo=CN_TZ).timestamp() * 1000
                            ),
                            "产品名称": "替考拉宁",
                            "出库量": 3.0,
                            "用途": "销售",
                        },
                    },
                    {
                        "record_id": "out2",
                        "fields": {
                            "出库日期": "2026-09-20",
                            "产品名称": "替考拉宁",
                            "出库量": "2.5kg",
                            "用途": "销售",
                        },
                    },
                ],
            }
        )
        movements = await fetch_day_movements(adapter, day=date(2026, 9, 20))
        assert movements.inbound_count == 2
        assert movements.inbound_qty == 12.0
        assert movements.inbound_by_product == [("达托霉素", 12.0)]
        assert movements.outbound_count == 2
        assert movements.outbound_qty == 5.5
        assert movements.outbound_by_product == [("替考拉宁", 5.5)]


class TestFetchQualityDistribution:
    async def test_counts_by_status_with_window(self) -> None:
        adapter = FakeFinishedAdapter(
            {
                "finished_receipt": [
                    _receipt_row("a", day=date(2026, 9, 1), status="合格"),
                    _receipt_row("b", day=date(2026, 9, 2), status="待处理"),
                    _receipt_row("c", day=date(2026, 9, 3), status="待处理"),
                    _receipt_row("d", day=date(2026, 9, 4), status="待检"),
                    _receipt_row("e", day=date(2026, 5, 1), status="待处理"),  # 窗口外
                    _receipt_row("f", day=None, status="退货"),  # 无日期跳过
                ],
            }
        )
        quality = await fetch_quality_distribution(adapter, since=date(2026, 8, 1))
        assert quality.get("合格") == 1
        assert quality.get("待处理") == 2
        assert quality.get("待检") == 1
        assert quality.get("退货") == 0


class TestFetchMonthFinishedIo:
    async def test_month_window_all_purposes(self) -> None:
        """月度合计：含头不含尾窗口 + 全用途口径（月报是出入库信息）。"""
        adapter = FakeFinishedAdapter(
            {
                "finished_receipt": [
                    _receipt_row("in1", day=date(2026, 9, 3), qty=5.0),
                    _receipt_row("in2", day=date(2026, 9, 30), qty=7.5),
                    _receipt_row("prev", day=date(2026, 8, 31), qty=99.0),  # 上月
                    _receipt_row("next", day=date(2026, 10, 1), qty=50.0),  # 下月
                    _receipt_row("nodate", day=None, qty=1.0),  # 无日期跳过
                ],
                "finished_outbound": [
                    {
                        "record_id": "out1",
                        "fields": {
                            "出库日期": "2026-09-10",
                            "产品名称": "替考拉宁",
                            "出库量": 3.0,
                            "用途": "销售",
                        },
                    },
                    {
                        "record_id": "out2",
                        "fields": {
                            "出库日期": "2026-09-21",
                            "产品名称": "替考拉宁",
                            "出库量": "2.5kg",
                            "用途": "车间领用",  # 全用途：非销售也计
                        },
                    },
                    {
                        "record_id": "out3",
                        "fields": {
                            "出库日期": "2026-10-01",
                            "产品名称": "替考拉宁",
                            "出库量": 8.0,
                            "用途": "销售",
                        },
                    },
                ],
            }
        )
        io = await fetch_month_finished_io(adapter, year=2026, month=9)
        assert io.inbound_count == 2
        assert io.inbound_qty == 12.5
        assert io.outbound_count == 2
        assert io.outbound_qty == 5.5

    async def test_empty_month(self) -> None:
        adapter = FakeFinishedAdapter({})
        io = await fetch_month_finished_io(adapter, year=2026, month=9)
        assert io.inbound_count == 0 and io.inbound_qty == 0.0
        assert io.outbound_count == 0 and io.outbound_qty == 0.0


# ═══════════════════════════════════════════════════════════════
# 生成器 dry_run（卡片结构）
# ═══════════════════════════════════════════════════════════════


def _element_texts(card: dict[str, Any]) -> str:
    return "\n".join(
        str(el.get("content") or "") for el in card.get("body", {}).get("elements", [])
    )


@pytest.fixture
def patch_finished_adapter(monkeypatch: pytest.MonkeyPatch):
    """把 generators 内部取用的 WarehouseBitableAdapter 替换为桩工厂。"""

    def _install(tables: dict[str, list[dict[str, Any]]]) -> FakeFinishedAdapter:
        fake = FakeFinishedAdapter(tables)
        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: fake,
        )
        return fake

    return _install


class TestFinishedDailySummaryGenerator:
    async def test_card_contains_daily_numbers(
        self, db_session, patch_finished_adapter
    ) -> None:
        patch_finished_adapter(
            {
                "finished_receipt": [
                    _receipt_row("a", day=date(2026, 9, 20), qty=5.0, status="合格"),
                    _receipt_row("b", day=date(2026, 9, 2), qty=1.0, status="待处理"),
                ],
                "finished_outbound": [
                    {
                        "record_id": "o",
                        "fields": {
                            "出库日期": int(
                                datetime(2026, 9, 20, tzinfo=CN_TZ).timestamp() * 1000
                            ),
                            "产品名称": "达托霉素",
                            "出库量": 4.0,
                        },
                    },
                ],
            }
        )
        card = await generators._generate_finished_daily_summary(db_session, NOW)
        assert card["header"]["title"]["content"] == "成品每日汇总 · 2026-09-20"
        assert card["header"]["template"] == "orange"  # 有待处理 → 提醒色
        text = _element_texts(card)
        assert "1 笔 / 5" in text
        assert "待处理 1" in text

    async def test_degrades_when_base_unreadable(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class BoomAdapter:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                raise RuntimeError("base down")

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            BoomAdapter,
        )
        card = await generators._generate_finished_daily_summary(db_session, NOW)
        assert card["header"]["template"] == "yellow"
        assert "暂不可读" in _element_texts(card)


class TestInvoiceFourStateGenerator:
    async def test_card_contains_states_and_detail(
        self, db_session, patch_finished_adapter
    ) -> None:
        patch_finished_adapter(
            {
                "daily_sales_summary": [
                    {
                        "record_id": "b1",
                        "fields": {
                            "销售日期": int(
                                datetime(2026, 9, 10, tzinfo=CN_TZ).timestamp() * 1000
                            ),
                            "产品名称": "达托霉素",
                            "品规": "DT高规",
                            "销售客户": "Hikma Jordan",
                            "出库量-开票工作流使用": 20.0,
                            "开票数量": None,
                        },
                    },
                    {
                        "record_id": "ok",
                        "fields": {
                            "销售日期": int(
                                datetime(2026, 9, 11, tzinfo=CN_TZ).timestamp() * 1000
                            ),
                            "产品名称": "替考拉宁",
                            "品规": "TE",
                            "销售客户": "REIG",
                            "出库量-开票工作流使用": 5.0,
                            "开票数量": 5.0,
                        },
                    },
                ],
            }
        )
        card = await generators._generate_invoice_four_state(db_session, NOW)
        assert card["header"]["title"]["content"].startswith("开票四态 · 2026-09-21")
        assert card["header"]["template"] == "orange"
        text = _element_texts(card)
        assert "已开票已发货 1 笔 / 5" in text
        assert "发货未开票 1 笔 / 20" in text
        assert "Hikma Jordan｜达托霉素" in text

    async def test_green_when_no_unbilled(
        self, db_session, patch_finished_adapter
    ) -> None:
        patch_finished_adapter({"daily_sales_summary": []})
        card = await generators._generate_invoice_four_state(db_session, NOW)
        assert card["header"]["template"] == "green"
        assert "暂无发货未开票项" in _element_texts(card)
