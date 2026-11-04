"""T2 直读 /movements + /materials 单测与 API 双分支（不触网）。"""

from __future__ import annotations

from typing import Any

import pytest


class FakeMovementAdapter:
    """按 table_key 返回单页记录。"""

    def __init__(self, by_table: dict[str, list[dict]]) -> None:
        self.by_table = by_table

    async def search_records_page(
        self, table_key: str, *, field_names: list[str] | None = None,
        limit: int = 500, page_token: str | None = None,
    ) -> dict[str, Any]:
        return {"records": self.by_table.get(table_key, []), "page_token": ""}


class TestFetchMovements:
    async def test_merge_direction_and_code_backfill(self) -> None:
        from app.modules.warehouse.direct import reader

        adapter = FakeMovementAdapter({
            "material_receipt": [
                {"record_id": "recv1", "fields": {
                    "代码": "10101", "物料名称": "磷酸二氢钾", "物料批号": "B1",
                    "入库数量": 100, "单位": "Kg", "入库日期": 1766000000000,
                    "物料大类": "原辅料",
                }},
                {"record_id": "recv2", "fields": {
                    "代码": "", "物料名称": "无代码行", "入库数量": 0,
                    "入库日期": None,  # 脏行：数量/日期缺失 → 跳过
                }},
            ],
            "material_outbound": [
                {"record_id": "otb1", "fields": {
                    # 无代码列；带规格后缀名 + 名称字段兜底
                    "物料名称": "磷酸二氢钾(工业级)", "名称": "磷酸二氢钾",
                    "物料批号": "B1", "出库数量": 40, "单位": "Kg",
                    "领用日期": "1767000000000", "物料大类": "原辅料",
                }},
                {"record_id": "otb2", "fields": {
                    "物料名称": "完全未知名", "出库数量": 5, "单位": "个",
                    "领用日期": "2026-10-01", "物料大类": "包材",
                }},
            ],
        })
        views = await reader.fetch_movements(adapter)
        assert len(views) == 3  # recv 脏行跳过
        by_dir = {v.direction: v for v in views if v.record_id != "otb2"}
        assert by_dir["inbound"].code == "10101"
        # 后缀剥离后命中 receipt 名称索引 → 代码回填
        assert by_dir["outbound"].code == "10101"
        assert by_dir["outbound"].source_type == "production"
        # 倒序（新在前：otb2=2026-10-01 晚于 otb1=2025-12）
        assert views[0].record_id == "otb2"
        # 毫秒字符串日期解析成功
        assert next(v for v in views if v.record_id == "otb1").occurred_at.year == 2025


@pytest.fixture
def direct_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.warehouse.direct import reader, service
    from app.modules.warehouse.direct import config as direct_config

    monkeypatch.setattr(direct_config, "direct_read_enabled", lambda: True)
    monkeypatch.setattr(direct_config, "cache_ttl_seconds", lambda: 0)

    async def _fake_movements(adapter: Any = None) -> list[Any]:
        from datetime import UTC, datetime

        from app.modules.warehouse.direct.views import MovementView

        return [
            MovementView(
                record_id="recvX1", direction="inbound", source_type="purchase",
                code="10101", name="磷酸二氢钾", batch_no="B1",
                quantity=100.0, unit="Kg",
                occurred_at=datetime(2026, 10, 2, tzinfo=UTC),
                category_cn="原辅料",
            ),
            MovementView(
                record_id="otbX1", direction="outbound", source_type="production",
                code="10101", name="磷酸二氢钾(工业级)", batch_no="B1",
                quantity=40.0, unit="Kg",
                occurred_at=datetime(2026, 10, 5, tzinfo=UTC),
                category_cn="原辅料",
            ),
        ]

    async def _fake_materials(adapter: Any = None) -> list[Any]:
        from app.modules.warehouse.direct.views import MaterialView

        return [
            MaterialView(record_id="recM1", code="10101", name="磷酸二氢钾",
                         category_cn="原辅料", spec="25Kg/包"),
        ]

    monkeypatch.setattr(reader, "fetch_movements", _fake_movements)
    monkeypatch.setattr(reader, "fetch_materials", _fake_materials)

    async def _fake_stocks(adapter: Any = None) -> list[Any]:
        return []  # materials_page 的单位回填不触网

    monkeypatch.setattr(reader, "fetch_stocks", _fake_stocks)
    service.movement_cache.invalidate()
    service.material_cache.invalidate()
    service.stock_cache.invalidate()


class TestMovementsDirectAPI:
    async def test_shape_and_filters(self, api_context: Any, direct_on: None) -> None:
        client, _ = api_context
        resp = await client.get(
            "/api/v1/warehouse/movements?direction=outbound&keyword=磷酸二氢钾"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["mode"] == "direct"
        assert body["meta"]["total"] == 1
        row = body["data"][0]
        assert set(row.keys()) == {
            "id", "movement_no", "direction", "source_type", "material_id",
            "material_code", "material_name", "batch_no", "quantity", "unit",
            "location_id", "location_code", "location_name", "occurred_at",
            "remark", "created_at",
        }
        assert row["direction"] == "outbound"
        assert row["movement_no"].startswith("OTB-")

    async def test_material_id_resolves_to_code(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        resp = await client.get(
            "/api/v1/warehouse/movements?material_id=recM1"
        )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 2  # 该代码全部流水

    async def test_movement_no_keyword_hit(
        self, api_context: Any, direct_on: None,
    ) -> None:
        client, _ = api_context
        resp = await client.get("/api/v1/warehouse/movements?keyword=RCPT-recvX1")
        assert resp.json()["meta"]["total"] == 1


class TestMaterialsDirectAPI:
    async def test_shape(self, api_context: Any, direct_on: None) -> None:
        client, _ = api_context
        resp = await client.get("/api/v1/warehouse/materials")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["mode"] == "direct"
        assert body["meta"]["total"] == 1
        row = body["data"][0]
        assert set(row.keys()) == {
            "id", "code", "name", "category", "spec", "unit",
            "safety_stock", "remark", "created_at", "updated_at",
        }
        assert row["id"] == "recM1"
        assert row["category"] == "raw"
        assert row["spec"] == "25Kg/包"
