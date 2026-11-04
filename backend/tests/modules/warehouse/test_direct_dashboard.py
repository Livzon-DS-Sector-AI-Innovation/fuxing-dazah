"""T3 直读概览/驾驶舱聚合测试（fixture 数据不触网）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

CN_TZ = ZoneInfo("Asia/Shanghai")


def _mk_stock(code: str, name: str, qty: float, category_cn: str = "原辅料") -> Any:
    from app.modules.warehouse.direct.views import StockView

    return StockView(
        record_id=f"recS{code}", code=code, name=name, batch_no=f"{code}-B",
        quantity=qty, unit="Kg", expiry_date=None, status="normal",
        qc_sample_status=None, qc_report_status=None, qc_release_status=None,
        category_cn=category_cn,
    )


def _mk_movement(
    direction: str, code: str, name: str, qty: float, days_ago: int
) -> Any:
    from app.modules.warehouse.direct.views import MovementView

    occurred = datetime.now(CN_TZ).astimezone(UTC) - timedelta(days=days_ago)
    return MovementView(
        record_id=f"recM{direction}{code}{days_ago}", direction=direction,
        source_type="purchase" if direction == "inbound" else "production",
        code=code, name=name, batch_no=f"{code}-B", quantity=qty, unit="Kg",
        occurred_at=occurred, category_cn="原辅料",
    )


class TestAnalytics:
    def test_trend_cn_day_slots(self) -> None:
        from app.modules.warehouse.direct import analytics

        movements = [
            _mk_movement("inbound", "A", "甲", 10, days_ago=0),   # 今天
            _mk_movement("outbound", "A", "甲", 4, days_ago=1),   # 昨天
            _mk_movement("inbound", "B", "乙", 7, days_ago=40),   # 窗口外
        ]
        trend = analytics.movement_trend(movements, 7)
        assert len(trend) == 7
        today_slot = trend[-1]
        assert today_slot["inbound"] == 10.0 and today_slot["outbound"] == 0.0
        yesterday = trend[-2]
        assert yesterday["outbound"] == 4.0
        assert all(slot["inbound"] == 0.0 for slot in trend[:-2][:5])

    def test_distribution_and_low_stock(self) -> None:
        from app.modules.warehouse.direct import analytics

        stocks = [
            _mk_stock("A", "甲", 10), _mk_stock("A2", "甲2", 5),
            _mk_stock("P", "标签", 3, category_cn="包材"),
        ]
        dist = analytics.stock_distribution(stocks)
        assert dist["by_category"] == [
            {"category": "raw", "total_quantity": 15.0},
            {"category": "packaging", "total_quantity": 3.0},
        ]
        assert dist["by_location_type"] == []
        # 呆滞：A 最后入库 100 天前且仍有库存 → idle 命中；B 3 天前不命中
        movements = [
            _mk_movement("inbound", "A", "甲", 10, days_ago=100),
            _mk_movement("inbound", "P", "标签", 3, days_ago=3),
        ]
        top = analytics.low_stock_top(stocks, movements, limit=10)
        assert top["low_stock"] == []
        assert len(top["idle"]) == 1
        item = top["idle"][0]
        assert item["material_code"] == "A"
        assert item["days_idle"] >= 90

    async def test_summary_shape(self, db_session: Any) -> None:
        from app.modules.warehouse.direct import analytics

        stocks = [_mk_stock("A", "甲", 12.5)]
        movements = [
            _mk_movement("inbound", "A", "甲", 30, days_ago=0),
            _mk_movement("outbound", "A", "甲", 5, days_ago=0),
            _mk_movement("inbound", "A", "甲", 8, days_ago=1),
        ]
        data = await analytics.summary(stocks, movements, 3, db_session)
        assert set(data.keys()) == {
            "total_quantity", "total_quantity_change", "material_count",
            "stock_sku_count", "today_inbound_quantity", "today_inbound_count",
            "today_outbound_quantity", "today_outbound_count",
            "yesterday_inbound_quantity", "yesterday_outbound_quantity",
            "low_stock_count", "draft_stocktake_count", "summary_text",
        }
        assert data["total_quantity"] == 12.5
        assert data["material_count"] == 3
        assert data["stock_sku_count"] == 1
        assert data["today_inbound_quantity"] == 30.0
        assert data["today_outbound_quantity"] == 5.0
        assert data["yesterday_inbound_quantity"] == 8.0
        assert data["total_quantity_change"] is None
        assert "今日入库 1 笔共 30" in data["summary_text"]

    async def test_overview_shape(self, db_session: Any) -> None:
        from app.modules.warehouse.direct import analytics

        data = await analytics.overview([_mk_stock("A", "甲", 1)], [], 2, db_session)
        assert set(data.keys()) == {
            "material_count", "location_count", "stock_sku_count",
            "low_stock_materials", "today_inbound_quantity",
            "today_outbound_quantity",
        }


@pytest.fixture
def direct_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.warehouse.direct import reader, service
    from app.modules.warehouse.direct import config as direct_config

    monkeypatch.setattr(direct_config, "direct_read_enabled", lambda: True)
    monkeypatch.setattr(direct_config, "cache_ttl_seconds", lambda: 0)

    async def _stocks(adapter: Any = None) -> list[Any]:
        return [_mk_stock("A", "甲", 10), _mk_stock("P", "标签", 3, "包材")]

    async def _movements(adapter: Any = None) -> list[Any]:
        return [_mk_movement("inbound", "A", "甲", 10, days_ago=0)]

    async def _materials(adapter: Any = None) -> list[Any]:
        return []

    monkeypatch.setattr(reader, "fetch_stocks", _stocks)
    monkeypatch.setattr(reader, "fetch_movements", _movements)
    monkeypatch.setattr(reader, "fetch_materials", _materials)
    service.stock_cache.invalidate()
    service.movement_cache.invalidate()
    service.material_cache.invalidate()


class TestDashboardDirectAPI:
    async def test_summary_and_trend_meta(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        r = await client.get("/api/v1/warehouse/dashboard/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["mode"] == "direct"
        assert body["data"]["total_quantity"] == 13.0
        r2 = await client.get("/api/v1/warehouse/dashboard/movement-trend?days=3")
        assert r2.json()["meta"]["mode"] == "direct"
        assert r2.json()["data"][-1]["inbound"] == 10.0

    async def test_gate_off_has_no_mode(self, api_context: Any) -> None:
        """conftest 钉 0：镜像路径，meta 无 mode。"""
        client, _ = api_context
        r = await client.get("/api/v1/warehouse/dashboard/summary")
        assert r.status_code == 200
        assert (r.json().get("meta") or {}).get("mode") is None
