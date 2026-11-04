"""/stocks 直读分支 API 测试（2026-11-04 直读改造）。

开关打桩 + fake reader 注入（不触网）；conftest 已把直读开关钉 0，
镜像分支（既有行为）由既有测试覆盖，这里补一个「开关 0 无 meta.mode」
的反向断言 + 三态变更直读拒绝。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_stock,
)

STOCK_VIEW = {
    "record_id": "recAAA", "code": "10101", "name": "碳酸钠",
    "batch_no": "10101-260101", "quantity": 25.5, "unit": "Kg",
    "expiry_date": date(2028, 3, 1), "status": "normal",
    "qc_sample_status": "已取样", "qc_report_status": "已出报（合格）",
    "qc_release_status": "放行", "category_cn": "原辅料",
}


def _fake_stock_view(**overrides: Any) -> Any:
    from app.modules.warehouse.direct.views import StockView

    return StockView(**{**STOCK_VIEW, **overrides})


@pytest.fixture
def direct_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """直读开 + reader 注入 fixture 数据 + 缓存关（每次直读确定性）。"""
    from app.modules.warehouse.direct import reader, service
    from app.modules.warehouse.direct import config as direct_config

    monkeypatch.setattr(direct_config, "direct_read_enabled", lambda: True)
    monkeypatch.setattr(direct_config, "cache_ttl_seconds", lambda: 0)

    async def _fake_fetch(adapter: Any = None) -> list[Any]:
        return [
            _fake_stock_view(),
            _fake_stock_view(record_id="recBBB", code="20201", name="标签纸",
                             batch_no="20201-260201", quantity= 3, unit="个",
                             status="quarantine", category_cn="包材"),
        ]

    monkeypatch.setattr(reader, "fetch_stocks", _fake_fetch)
    service.stock_cache.invalidate()


class TestStocksDirectBranch:
    async def test_shape_matches_mirror_serialization(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        resp = await client.get("/api/v1/warehouse/stocks?page=1&page_size=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["mode"] == "direct"
        assert body["meta"]["total"] == 2
        assert body["meta"]["page"] == 1
        row = body["data"][0]
        # 与 schemas.StockResponse 逐键对齐（+QC 三列）
        assert set(row.keys()) == {
            "id", "material_id", "material_code", "material_name", "category",
            "unit", "safety_stock", "batch_no", "location_id", "location_code",
            "location_name", "expiry_date", "quantity", "status",
            "qc_sample_status", "qc_report_status", "qc_release_status",
        }
        assert row["id"] == "recAAA"
        assert row["material_code"] == "10101"
        assert row["qc_release_status"] == "放行"
        assert row["category"] == "raw"

    async def test_filters_keyword_and_status(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        resp = await client.get(
            "/api/v1/warehouse/stocks?keyword=标签纸&status=quarantine"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["material_name"] == "标签纸"
        assert data[0]["category"] == "packaging"

    async def test_location_filter_ignored_with_meta_note(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        resp = await client.get(
            "/api/v1/warehouse/stocks?location_id=00000000-0000-0000-0000-000000000001"
        )
        assert resp.status_code == 200
        assert "location_filter_ignored" in resp.json()["meta"]
        assert resp.json()["meta"]["total"] == 2  # 未因库位过滤丢行

    async def test_gate_off_no_direct_meta(
        self, api_context: Any, db_session: Any,
    ) -> None:
        """开关 0（conftest 钉死）：走镜像路径，meta 无 mode=direct。"""
        client, _ = api_context
        material = await create_material(db_session)
        location = await create_location(db_session)
        await create_stock(db_session, material, location, quantity=5)
        resp = await client.get("/api/v1/warehouse/stocks")
        assert resp.status_code == 200
        assert resp.json()["meta"].get("mode") is None


class TestStockStatusDirectRejection:
    async def test_direct_mode_rejects_status_change(
        self, api_context: Any, direct_on: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, _ = api_context
        from tests.modules.warehouse.conftest import WAREHOUSE_PERMS

        async def _perms(uid: str, db: object) -> set[str]:
            return WAREHOUSE_PERMS | {"warehouse:intelligence:update"}

        monkeypatch.setattr(
            "app.platform.permission.deps.get_user_permissions", _perms
        )
        resp = await client.post(
            "/api/v1/warehouse/stocks/recAAA/status",
            json={"new_status": "quarantine", "reason": "直读测试"},
        )
        assert resp.status_code == 400
        assert "直读模式" in resp.json()["message"]
