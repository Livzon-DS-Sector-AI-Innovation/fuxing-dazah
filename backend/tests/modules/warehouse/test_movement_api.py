"""出入库 API 端点测试：库存联动、库存不足校验、撤销冲销。"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_movement,
    create_stock,
)


async def _stock_quantity(client: AsyncClient, material_id: str) -> float | None:
    resp = await client.get(
        "/api/v1/warehouse/stocks", params={"page_size": 200}
    )
    for item in resp.json()["data"]:
        if item["material_id"] == material_id:
            return item["quantity"]
    return None


class TestCreateMovement:
    async def test_inbound_creates_stock(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        resp = await client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "batch_no": "B20260901",
                "quantity": 25,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["movement_no"].startswith("IN-")
        assert data["unit"] == material.unit
        assert await _stock_quantity(client, str(material.id)) == 25

    async def test_outbound_insufficient_returns_400(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        resp = await client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "outbound",
                "source_type": "sale",
                "material_id": str(material.id),
                "quantity": 10,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 400

    async def test_outbound_decrements_stock(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_stock(db, material, location, quantity=50)
        resp = await client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "outbound",
                "source_type": "production",
                "material_id": str(material.id),
                "quantity": 12.5,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 201
        assert await _stock_quantity(client, str(material.id)) == 37.5

    async def test_unknown_material_returns_404(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        location = await create_location(db)
        resp = await client.post(
            "/api/v1/warehouse/movements",
            json={
                "direction": "inbound",
                "source_type": "other",
                "material_id": "00000000-0000-0000-0000-000000000000",
                "quantity": 1,
                "location_id": str(location.id),
            },
        )
        assert resp.status_code == 404


class TestDeleteMovement:
    async def test_delete_inbound_reverses_stock(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_stock(db, material, location, quantity=30)
        # 工厂直接插入的 movement 不经过 service，库存未含该入库；
        # 删除时按"该入库已生效"反向扣减 → 30 - 20 = 10
        movement = await create_movement(
            db, material, location, direction="inbound", quantity=20
        )
        resp = await client.delete(f"/api/v1/warehouse/movements/{movement.id}")
        assert resp.status_code == 200
        assert await _stock_quantity(client, str(material.id)) == 10

    async def test_delete_outbound_reverses_stock(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_stock(db, material, location, quantity=10)
        movement = await create_movement(
            db, material, location, direction="outbound", quantity=4
        )
        resp = await client.delete(f"/api/v1/warehouse/movements/{movement.id}")
        assert resp.status_code == 200
        assert await _stock_quantity(client, str(material.id)) == 14

    async def test_delete_inbound_when_stock_consumed_returns_400(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """入库后物料已被全部出库，撤销该入库会导致负库存，应拒绝。"""
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        for payload in (
            {
                "direction": "inbound",
                "source_type": "purchase",
                "material_id": str(material.id),
                "quantity": 50,
                "location_id": str(location.id),
            },
            {
                "direction": "outbound",
                "source_type": "sale",
                "material_id": str(material.id),
                "quantity": 50,
                "location_id": str(location.id),
            },
        ):
            resp = await client.post("/api/v1/warehouse/movements", json=payload)
            assert resp.status_code == 201
        movements = (
            await client.get(
                "/api/v1/warehouse/movements", params={"keyword": material.code}
            )
        ).json()["data"]
        inbound_id = next(
            m["id"] for m in movements if m["direction"] == "inbound"
        )
        resp = await client.delete(f"/api/v1/warehouse/movements/{inbound_id}")
        assert resp.status_code == 400

    async def test_delete_adjust_forbidden(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        movement = await create_movement(
            db,
            material,
            location,
            direction="adjust",
            source_type="stocktake",
            quantity=1,
        )
        resp = await client.delete(f"/api/v1/warehouse/movements/{movement.id}")
        assert resp.status_code == 400


class TestListMovements:
    async def test_direction_filter(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_movement(db, material, location, direction="inbound", quantity=1)
        await create_movement(db, material, location, direction="outbound", quantity=1)
        resp = await client.get(
            "/api/v1/warehouse/movements",
            params={"direction": "outbound", "keyword": material.code},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["direction"] == "outbound"
