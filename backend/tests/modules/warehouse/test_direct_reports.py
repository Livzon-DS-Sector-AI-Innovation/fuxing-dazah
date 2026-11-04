"""T4 直读报表族测试（fixture 不触网）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

CN_TZ = ZoneInfo("Asia/Shanghai")


def _mv(direction: str, code: str, name: str, qty: float, at: datetime) -> Any:
    from app.modules.warehouse.direct.views import MovementView

    return MovementView(
        record_id=f"r{direction}{code}{int(at.timestamp())}", direction=direction,
        source_type="purchase" if direction == "inbound" else "production",
        code=code, name=name, batch_no=f"{code}-B", quantity=qty, unit="Kg",
        occurred_at=at, category_cn="原辅料",
    )


def _stock(code: str, qty: float) -> Any:
    from app.modules.warehouse.direct.views import StockView

    return StockView(
        record_id=f"s{code}", code=code, name=f"物料{code}", batch_no=f"{code}-B",
        quantity=qty, unit="Kg", expiry_date=None, status="normal",
        qc_sample_status=None, qc_report_status=None, qc_release_status=None,
    )


def _at_cn(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, tzinfo=CN_TZ).astimezone(UTC)


class TestReportAnalytics:
    def test_monthly_report(self) -> None:
        from app.modules.warehouse.direct import analytics

        movements = [
            _mv("inbound", "A", "甲", 10, _at_cn(2026, 10, 5)),
            _mv("inbound", "A", "甲", 5, _at_cn(2026, 10, 20)),
            _mv("outbound", "A", "甲", 3, _at_cn(2026, 10, 21)),
            _mv("outbound", "B", "乙", 7, _at_cn(2026, 11, 1)),   # 窗口外
        ]
        report = analytics.monthly_report(movements, 2026, 10)
        assert report["summary"] == {
            "inbound_count": 2, "inbound_qty": 15.0,
            "outbound_count": 1, "outbound_qty": 3.0,
        }
        assert len(report["items"]) == 1
        item = report["items"][0]
        assert (item["material_code"], item["inbound_qty"], item["outbound_qty"]) == ("A", 15.0, 3.0)

    def test_annual_report(self) -> None:
        from app.modules.warehouse.direct import analytics

        movements = [
            _mv("inbound", "A", "甲", 10, _at_cn(2026, 1, 5)),
            _mv("outbound", "A", "甲", 4, _at_cn(2026, 12, 30)),
            _mv("inbound", "B", "乙", 9, _at_cn(2025, 12, 31)),   # 年外
        ]
        report = analytics.annual_report(movements, 2026)
        assert report["summary"]["inbound_qty"] == 10.0
        assert len(report["months"]) == 12
        assert report["months"][0]["inbound_qty"] == 10.0
        assert report["months"][11]["outbound_qty"] == 4.0
        assert report["items"][0]["material_code"] == "A"

    def test_turnover_and_consumption(self) -> None:
        from app.modules.warehouse.direct import analytics

        movements = [
            _mv("outbound", "A", "甲", 10, datetime.now(UTC) - timedelta(days=1)),
            _mv("outbound", "B", "乙", 5, datetime.now(UTC) - timedelta(days=1)),
            _mv("outbound", "C", "旧", 99, datetime.now(UTC) - timedelta(days=100)),
        ]
        stocks = [_stock("A", 5), _stock("B", 0)]
        turnover = analytics.turnover_ranking(stocks, movements, days=30, limit=10)
        codes = [r["material_code"] for r in turnover]
        assert codes == ["A", "B"]          # C 窗口外；A(2.0) > B(None) 排序
        assert turnover[0]["turnover"] == 2.0
        assert turnover[1]["turnover"] is None
        consumption = analytics.consumption_ranking(movements, days=30, limit=10)
        assert [r["material_code"] for r in consumption] == ["A", "B"]

    def test_stock_report_and_batch_trace(self) -> None:
        from app.modules.warehouse.direct import analytics

        stocks = [_stock("A", 5), _stock("B", 0)]  # B 数量 0 不进报表
        rows, total = analytics.stock_report_rows(stocks, 1, 10)
        assert total == 1 and rows[0]["material_code"] == "A"
        assert rows[0]["location_name"] == ""
        movements = [
            _mv("inbound", "A", "甲", 10, _at_cn(2026, 10, 5)),
            _mv("outbound", "A", "甲", 3, _at_cn(2026, 10, 6)),
        ]
        trace = analytics.batch_trace(movements, "A", "A-B")
        assert len(trace["inbound_flows"]) == 1
        assert len(trace["outbound_flows"]) == 1
        assert trace["outbound_flows"][0]["movement_no"].startswith("OTB-")


@pytest.fixture
def direct_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.warehouse.direct import reader, service
    from app.modules.warehouse.direct import config as direct_config

    monkeypatch.setattr(direct_config, "direct_read_enabled", lambda: True)
    monkeypatch.setattr(direct_config, "cache_ttl_seconds", lambda: 0)

    async def _stocks(adapter: Any = None) -> list[Any]:
        return [_stock("A", 5), _stock("B", 0)]

    async def _movements(adapter: Any = None) -> list[Any]:
        return [
            _mv("inbound", "A", "甲", 10, _at_cn(2026, 10, 5)),
            _mv("outbound", "A", "甲", 3, _at_cn(2026, 10, 6)),
        ]

    async def _materials(adapter: Any = None) -> list[Any]:
        return []

    monkeypatch.setattr(reader, "fetch_stocks", _stocks)
    monkeypatch.setattr(reader, "fetch_movements", _movements)
    monkeypatch.setattr(reader, "fetch_materials", _materials)
    for cache in (service.stock_cache, service.movement_cache, service.material_cache):
        cache.invalidate()

    # conftest 权限集不含报表码——本文件 API 用例补齐所需权限
    async def _perms(uid: str, db: object) -> set[str]:
        return {
            "warehouse:reports:read", "warehouse:stock:read",
            "warehouse:movement:read", "warehouse:material:read",
        }

    monkeypatch.setattr(
        "app.platform.permission.deps.get_user_permissions", _perms
    )


class TestReportDirectAPI:
    async def test_monthly_and_stock(self, api_context: Any, direct_on: None) -> None:
        client, _ = api_context
        r = await client.get("/api/v1/warehouse/reports/monthly?year=2026&month=10")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["mode"] == "direct"
        assert body["data"]["summary"]["inbound_qty"] == 10.0
        r2 = await client.get("/api/v1/warehouse/reports/stock?page_size=10")
        body2 = r2.json()
        assert body2["meta"]["total"] == 1
        assert body2["data"][0]["material_code"] == "A"

    async def test_export_bytes(self, api_context: Any, direct_on: None) -> None:
        client, _ = api_context
        r = await client.get(
            "/api/v1/warehouse/reports/monthly/export?year=2026&month=10"
        )
        assert r.status_code == 200 and len(r.content) > 100
        r2 = await client.get("/api/v1/warehouse/reports/stock/export")
        assert r2.status_code == 200 and len(r2.content) > 100

    async def test_batch_trace_direct(self, api_context: Any, direct_on: None) -> None:
        client, _ = api_context
        r = await client.get(
            "/api/v1/warehouse/reports/batch-trace?material_code=A&batch_no=A-B"
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data["inbound_flows"]) == 1
        assert len(data["outbound_flows"]) == 1
