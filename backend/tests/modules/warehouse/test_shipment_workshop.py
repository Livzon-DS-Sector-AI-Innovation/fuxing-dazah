"""发货去向月度分析 + 车间周用量测试（V3.0 分期D Ticket 06，§4.8⑤/§4.4⑤）。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.warehouse.finished_data import (
    _parse_outbound_row,
    summarize_shipments,
)
from app.modules.warehouse.push_center import generators
from app.modules.warehouse.usage_data import (
    fetch_picking_rows,
    summarize_dept_usage,
)
from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_movement,
)

CN_TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=CN_TZ)  # 周一 09:00


def _outbound_row(
    record_id: str,
    *,
    day: date | None,
    customer: str = "Hikma Jordan",
    product: str = "达托霉素",
    qty: float | None = 10.0,
    purpose: str = "销售",
) -> Any:
    return _parse_outbound_row(
        {
            "record_id": record_id,
            "fields": {
                "出库日期": int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp() * 1000)
                if day
                else None,
                "产品名称": product,
                "品规": "DT高规",
                "产品批号": "DA2609001",
                "出库量": qty,
                "单位": "kg",
                "销售客户": customer,
                "用途": purpose,
            },
        }
    )


class TestSummarizeShipments:
    def test_customer_ranking_and_window(self) -> None:
        rows = [
            _outbound_row("a", day=date(2026, 9, 5), customer="REIG", qty=30.0),
            _outbound_row("b", day=date(2026, 9, 6), customer="Hikma Jordan", qty=10.0),
            _outbound_row("c", day=date(2026, 9, 7), customer="Hikma Jordan", qty=25.0),
            _outbound_row("d", day=date(2026, 8, 31), customer="REIG", qty=999.0),  # 上上月
            _outbound_row("e", day=date(2026, 9, 8), customer="can", qty=5.0,
                          purpose="客户小样"),  # 非销售用途
        ]
        current = summarize_shipments(rows, start=date(2026, 9, 1), end=date(2026, 10, 1))
        assert [c.customer for c in current] == ["Hikma Jordan", "REIG"]
        lead = current[0]
        assert lead.total_qty == 35.0
        assert lead.order_count == 2
        assert lead.product_totals == [("达托霉素", 35.0)]

    def test_product_breakdown_top5(self) -> None:
        rows = [
            _outbound_row(f"p{i}", day=date(2026, 9, 5), customer="REIG",
                          product=f"产品{i}", qty=float(i))
            for i in range(1, 8)
        ]
        current = summarize_shipments(rows, start=date(2026, 9, 1), end=date(2026, 10, 1))
        assert len(current[0].product_totals) == 5
        assert current[0].product_totals[0] == ("产品7", 7.0)


class FakePickingAdapter:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def search_records_page(self, table_key: str, **kwargs: Any) -> dict[str, Any]:
        assert table_key == "material_outbound"
        return {"records": self.rows, "total": len(self.rows), "page_token": None}


def _picking_raw(record_id: str, *, day: date | None, dept: str, name: str, qty: float) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "fields": {
            "物料名称(API)": name,
            "出库数量": qty,
            "领用部门": dept,
            "领用日期": int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp() * 1000)
            if day
            else None,
        },
    }


class TestWorkshopUsage:
    async def test_fetch_and_summarize(self) -> None:
        adapter = FakePickingAdapter([
            _picking_raw("p1", day=date(2026, 9, 29), dept="精制工程一部", name="硫酸", qty=100.0),
            _picking_raw("p2", day=date(2026, 10, 1), dept="精制工程一部", name="盐酸", qty=50.0),
            _picking_raw("p3", day=date(2026, 10, 2), dept="发酵工程一部", name="鱼蛋白胨", qty=20.0),
            _picking_raw("p4", day=date(2026, 9, 20), dept="精制工程一部", name="旧料", qty=999.0),  # 窗口外
        ])
        rows = await fetch_picking_rows(adapter)
        usages = summarize_dept_usage(rows, start=date(2026, 9, 28), end=date(2026, 10, 5))
        assert [u.department for u in usages] == ["精制工程一部", "发酵工程一部"]
        lead = usages[0]
        assert lead.order_count == 2
        assert lead.total_qty == 150.0
        assert lead.top_materials[0] == ("硫酸", 100.0)

    async def test_generator_card(self, db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = FakePickingAdapter([
            _picking_raw("p1", day=date(2026, 10, 1), dept="精制工程一部", name="硫酸", qty=100.0),
        ])
        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: adapter,
        )
        card = await generators._generate_workshop_weekly_usage(db_session, NOW)
        assert card["header"]["template"] == "blue"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "**精制工程一部** 1 笔 / 100" in text


class TestShipmentAnalysisGenerator:
    async def test_card_with_ranking_and_delta(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            _outbound_row("a1", day=date(2026, 9, 5), customer="REIG", qty=30.0),
            _outbound_row("a2", day=date(2026, 9, 6), customer="Hikma Jordan", qty=10.0),
            _outbound_row("a3", day=date(2026, 8, 5), customer="Hikma Jordan", qty=20.0),  # 上月环比基数
        ]

        class _Adapter:
            def __init__(self) -> None:
                pass

            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                # finished_outbound 行以原始 fields 形态返回（fetch 层解析）
                return {
                    "records": [
                        {
                            "record_id": r.record_id,
                            "fields": {
                                "出库日期": int(
                                    datetime(
                                        r.outbound_date.year,
                                        r.outbound_date.month,
                                        r.outbound_date.day,
                                        tzinfo=CN_TZ,
                                    ).timestamp()
                                    * 1000
                                ),
                                "产品名称": r.product_name,
                                "品规": "DT高规",
                                "产品批号": "DA2609001",
                                "出库量": r.qty,
                                "单位": "kg",
                                "销售客户": r.customer,
                                "用途": r.purpose,
                            },
                        }
                        for r in rows
                    ],
                    "total": len(rows),
                    "page_token": None,
                }

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            _Adapter,
        )

        async def _fake_llm(_prompt: str) -> str:
            return "桩解读：发货平稳。"

        monkeypatch.setattr(generators, "_llm_summarize", _fake_llm)
        card = await generators._generate_shipment_analysis(db_session, NOW)
        assert card["header"]["title"]["content"] == "发货去向分析 · 2026-09"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "客户排名 Top2" in text
        assert "REIG：30" in text
        assert "Hikma Jordan：10（1 笔，环比 -50%）" in text
        assert "桩解读" in text

    async def test_empty_month_shows_first_period_hint(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Adapter:
            def __init__(self) -> None:
                pass

            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                return {"records": [], "total": 0, "page_token": None}

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            _Adapter,
        )
        card = await generators._generate_shipment_analysis(db_session, NOW)
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "首期或当月无数据" in text

    async def test_base_failure_degrades_to_local(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        material = await create_material(db_session)
        location = await create_location(db_session)
        await create_movement(
            db_session, material, location, direction="outbound", quantity=Decimal("42"),
            occurred_at=datetime(2026, 10, 2, tzinfo=CN_TZ),
        )

        class _BoomAdapter:
            def __init__(self) -> None:
                pass

            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                raise RuntimeError("base down")

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            _BoomAdapter,
        )
        card = await generators._generate_workshop_weekly_usage(db_session, NOW)
        assert card["header"]["template"] == "yellow"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "本地流水口径" in text
        assert "42" in text
