"""有毒有害可燃探测器 API 端点功能测试。

契约与器具端点一致：201 新增、404 不存在、409 重复、分页 meta。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.modules.meter.conftest import create_gas_detector


class TestCreateGasDetector:
    async def test_create_returns_201(self, api_context: tuple[AsyncClient, Any]) -> None:
        """新增探测器应返回 201。"""
        client, _ = api_context
        resp = await client.post(
            "/api/v1/meter/gas-detectors",
            json={"instrument_name": "探测器API"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["instrument_name"] == "探测器API"

    async def test_duplicate_product_number_returns_409(self, api_context: tuple[AsyncClient, Any]) -> None:
        """产品编号重复应返回 409。"""
        client, db = api_context
        det = await create_gas_detector(db)
        resp = await client.post(
            "/api/v1/meter/gas-detectors",
            json={"instrument_name": "另一台", "product_number": det.product_number},
        )
        assert resp.status_code == 409


class TestListGasDetectors:
    async def test_paginated_list(self, api_context: tuple[AsyncClient, Any]) -> None:
        """列表应返回分页 meta。"""
        client, db = api_context
        dept = f"TEST-APIGD-{uuid4().hex[:8]}"
        await create_gas_detector(db, department=dept)
        resp = await client.get(
            "/api/v1/meter/gas-detectors", params={"department": dept}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1

    async def test_filter_options_include_overdue(self, api_context: tuple[AsyncClient, Any]) -> None:
        """筛选选项应包含"超期"且排第一。"""
        client, _ = api_context
        resp = await client.get("/api/v1/meter/gas-detectors/filter-options")
        assert resp.status_code == 200
        statuses = resp.json()["data"]["status"]
        assert statuses[0] == "超期"


class TestGetGasDetector:
    async def test_get_detail(self, api_context: tuple[AsyncClient, Any]) -> None:
        """详情应返回记录。"""
        client, db = api_context
        det = await create_gas_detector(db)
        resp = await client.get(f"/api/v1/meter/gas-detectors/{det.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == str(det.id)

    async def test_get_missing_returns_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """不存在的探测器应返回 404。"""
        client, _ = api_context
        resp = await client.get(f"/api/v1/meter/gas-detectors/{uuid4()}")
        assert resp.status_code == 404


class TestUpdateGasDetector:
    async def test_update_success(self, api_context: tuple[AsyncClient, Any]) -> None:
        """更新应返回修改后的字段。"""
        client, db = api_context
        det = await create_gas_detector(db)
        resp = await client.put(
            f"/api/v1/meter/gas-detectors/{det.id}", json={"installation_location": "三车间"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["installation_location"] == "三车间"


class TestDeleteGasDetector:
    async def test_delete_then_get_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """软删除后详情应返回 404。"""
        client, db = api_context
        det = await create_gas_detector(db)
        resp = await client.delete(f"/api/v1/meter/gas-detectors/{det.id}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/v1/meter/gas-detectors/{det.id}")
        assert resp.status_code == 404

    async def test_batch_delete(self, api_context: tuple[AsyncClient, Any]) -> None:
        """批量删除应返回删除数量。"""
        client, db = api_context
        a = await create_gas_detector(db)
        b = await create_gas_detector(db)
        resp = await client.post(
            "/api/v1/meter/gas-detectors/batch-delete",
            json={"ids": [str(a.id), str(b.id)]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted_count"] == 2


class TestGetGasDetectorIds:
    async def test_ids_endpoint_returns_all_ids(self, api_context: tuple[AsyncClient, Any]) -> None:
        """筛选条件下所有探测器 ID 应可通过 /gas-detectors/ids 获取。"""
        client, db = api_context
        dept = f"TEST-APIGD-{uuid4().hex[:8]}"
        a = await create_gas_detector(db, department=dept)
        b = await create_gas_detector(db, department=dept)
        resp = await client.get(
            "/api/v1/meter/gas-detectors/ids", params={"department": dept}
        )
        assert resp.status_code == 200
        ids = set(resp.json()["data"])
        assert ids == {str(a.id), str(b.id)}


class TestExportGasDetectors:
    async def test_export_excel(self, api_context: tuple[AsyncClient, Any]) -> None:
        """导出 Excel 应为 spreadsheetml 类型。"""
        client, db = api_context
        await create_gas_detector(db)
        resp = await client.get("/api/v1/meter/gas-detectors/export-excel")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]


class TestBatchCreateGasDetectorsAPI:
    async def test_batch_create(self, client_with_noop_commit: AsyncClient) -> None:
        """批量新增探测器应返回 created/skipped 统计。"""
        resp = await client_with_noop_commit.post(
            "/api/v1/meter/gas-detectors/batch",
            json={
                "items": [
                    {"instrument_name": "批量探测器1", "department": "安全部"},
                    {"instrument_name": "批量探测器2", "department": "安全部"},
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["created"] == 2
