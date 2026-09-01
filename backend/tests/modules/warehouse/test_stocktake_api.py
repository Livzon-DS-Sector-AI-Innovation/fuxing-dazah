"""盘点 API 端点测试：快照、实盘填写、确认调整库存、状态机约束。"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_stock,
)


async def _create_scope_stock(
    api_context: tuple[AsyncClient, Any],
) -> tuple[AsyncClient, Any, tuple[Any, Any, Any]]:
    """准备一个有库存的物料+库位，返回 (client, db, (material, location, stock_id))。"""
    client, db = api_context
    material = await create_material(db, name="盘点物料", unit="kg")
    location = await create_location(db, name="盘点库位")
    stock = await create_stock(db, material, location, quantity=100)
    return client, db, (material, location, stock)


class TestStocktakeLifecycle:
    async def test_create_without_stock_returns_400(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        location = await create_location(db)
        resp = await client.post(
            "/api/v1/warehouse/stocktakes",
            json={"scope_location_id": str(location.id)},
        )
        assert resp.status_code == 400

    async def test_create_snapshots_book_quantity(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db, (material, location, _stock) = await _create_scope_stock(api_context)
        resp = await client.post("/api/v1/warehouse/stocktakes", json={})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["status"] == "draft"
        assert data["stocktake_no"].startswith("ST-")
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["material_id"] == str(material.id)
        assert item["book_quantity"] == 100
        assert item["counted_quantity"] is None
        assert item["difference"] is None

    async def test_confirm_requires_all_counted(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db, (material, location, _stock) = await _create_scope_stock(api_context)
        stocktake = (
            await client.post("/api/v1/warehouse/stocktakes", json={})
        ).json()["data"]
        resp = await client.post(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}/confirm"
        )
        assert resp.status_code == 400

    async def test_confirm_posts_adjustments(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db, (material, location, _stock) = await _create_scope_stock(api_context)
        stocktake = (
            await client.post("/api/v1/warehouse/stocktakes", json={})
        ).json()["data"]
        item = stocktake["items"][0]

        # 实盘 96 → 盘亏 4
        resp = await client.put(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}",
            json={"items": [{"item_id": item["id"], "counted_quantity": 96}]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["items"][0]["difference"] == -4

        resp = await client.post(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}/confirm"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "confirmed"
        assert data["confirmed_at"]

        # 库存被调整为实盘值，且生成盘点调整流水
        resp = await client.get("/api/v1/warehouse/stocks")
        assert resp.json()["data"][0]["quantity"] == 96
        resp = await client.get(
            "/api/v1/warehouse/movements",
            params={"source_type": "stocktake", "keyword": material.code},
        )
        adjustments = resp.json()["data"]
        assert len(adjustments) == 1
        assert adjustments[0]["direction"] == "adjust"
        assert adjustments[0]["quantity"] == 4

    async def test_confirmed_cannot_update_or_reconfirm(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db, (material, location, _stock) = await _create_scope_stock(api_context)
        stocktake = (
            await client.post("/api/v1/warehouse/stocktakes", json={})
        ).json()["data"]
        item = stocktake["items"][0]
        await client.put(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}",
            json={"items": [{"item_id": item["id"], "counted_quantity": 100}]},
        )
        await client.post(f"/api/v1/warehouse/stocktakes/{stocktake['id']}/confirm")

        resp = await client.put(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}",
            json={"items": [{"item_id": item["id"], "counted_quantity": 1}]},
        )
        assert resp.status_code == 400
        resp = await client.post(
            f"/api/v1/warehouse/stocktakes/{stocktake['id']}/confirm"
        )
        assert resp.status_code == 400
        resp = await client.delete(f"/api/v1/warehouse/stocktakes/{stocktake['id']}")
        assert resp.status_code == 400

    async def test_delete_draft(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, db, _scope = await _create_scope_stock(api_context)
        stocktake = (
            await client.post("/api/v1/warehouse/stocktakes", json={})
        ).json()["data"]
        resp = await client.delete(f"/api/v1/warehouse/stocktakes/{stocktake['id']}")
        assert resp.status_code == 200
        resp = await client.get("/api/v1/warehouse/stocktakes")
        assert resp.json()["meta"]["total"] == 0
