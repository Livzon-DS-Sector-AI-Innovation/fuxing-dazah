"""物料主数据与库位 API 端点测试。

契约：统一响应包 {code,message,data,meta}；分页 meta {page,page_size,total}；
重复编码 409 / 不存在 404 / 删除后同编码可重建（部分唯一索引）。
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_stock,
    rand_code,
)


class TestMaterialApi:
    async def test_create_returns_201(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, _ = api_context
        resp = await client.post(
            "/api/v1/warehouse/materials",
            json={
                "code": rand_code("API"),
                "name": "无水乙醇",
                "category": "raw",
                "unit": "kg",
                "safety_stock": 10,
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "无水乙醇"
        assert data["safety_stock"] == 10

    async def test_duplicate_code_returns_409(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        resp = await client.post(
            "/api/v1/warehouse/materials",
            json={
                "code": material.code,
                "name": "重复编码",
                "category": "raw",
                "unit": "kg",
            },
        )
        assert resp.status_code == 409

    async def test_create_with_stock_after_delete_rebuild(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """删除后同编码可重建（部分唯一索引只约束未删除行）。"""
        client, db = api_context
        material = await create_material(db)
        resp = await client.delete(f"/api/v1/warehouse/materials/{material.id}")
        assert resp.status_code == 200
        resp = await client.post(
            "/api/v1/warehouse/materials",
            json={
                "code": material.code,
                "name": "重建物料",
                "category": "raw",
                "unit": "kg",
            },
        )
        assert resp.status_code == 201

    async def test_delete_blocked_when_stock_exists(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_stock(db, material, location, quantity=5)
        resp = await client.delete(f"/api/v1/warehouse/materials/{material.id}")
        assert resp.status_code == 400

    async def test_list_keyword_filter(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db, name="独一味关键词物料")
        await create_material(db)
        resp = await client.get(
            "/api/v1/warehouse/materials", params={"keyword": "独一味关键词"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == str(material.id)

    async def test_update_fields(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, db = api_context
        material = await create_material(db)
        resp = await client.put(
            f"/api/v1/warehouse/materials/{material.id}",
            json={"name": "改名物料", "safety_stock": 3.5},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "改名物料"
        assert data["safety_stock"] == 3.5

    async def test_get_not_found(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, _ = api_context
        resp = await client.put(
            "/api/v1/warehouse/materials/00000000-0000-0000-0000-000000000000",
            json={"name": "不存在"},
        )
        assert resp.status_code == 404


class TestLocationApi:
    async def test_create_and_list(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, db = api_context
        location = await create_location(db, name="原料一号库")
        resp = await client.get("/api/v1/warehouse/locations")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["data"]]
        assert str(location.id) in ids

    async def test_duplicate_code_returns_409(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        location = await create_location(db)
        resp = await client.post(
            "/api/v1/warehouse/locations",
            json={"code": location.code, "name": "重复库位"},
        )
        assert resp.status_code == 409

    async def test_delete_blocked_when_stock_exists(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        client, db = api_context
        material = await create_material(db)
        location = await create_location(db)
        await create_stock(db, material, location, quantity=1)
        resp = await client.delete(f"/api/v1/warehouse/locations/{location.id}")
        assert resp.status_code == 400

    async def test_delete_without_stock(self, api_context: tuple[AsyncClient, Any]) -> None:
        client, db = api_context
        location = await create_location(db)
        resp = await client.delete(f"/api/v1/warehouse/locations/{location.id}")
        assert resp.status_code == 200
