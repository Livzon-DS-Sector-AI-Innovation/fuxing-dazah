"""标准计量器具 API 端点功能测试。

契约：统一响应包 {code,message,data,meta}；分页 meta {page,page_size,total}；
重复 409 / 不存在 404。预置数据与请求共用 api_context 的同一 session，
批量新增（内部 commit）用 client_with_noop_commit 隔离。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.modules.meter.conftest import create_instrument


class TestCreateInstrument:
    async def test_create_returns_201(self, api_context: tuple[AsyncClient, Any]) -> None:
        """新增器具应返回 201 与完整字段。"""
        client, _ = api_context
        resp = await client.post(
            "/api/v1/meter/instruments",
            json={"asset_number": f"A-{uuid4().hex[:8]}", "instrument_name": "压力表API"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["instrument_name"] == "压力表API"
        assert data["id"]

    async def test_duplicate_asset_number_returns_409(self, api_context: tuple[AsyncClient, Any]) -> None:
        """资产编号重复应返回 409。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.post(
            "/api/v1/meter/instruments",
            json={"asset_number": inst.asset_number, "instrument_name": "另一块"},
        )
        assert resp.status_code == 409

    async def test_missing_required_fields_returns_422(self, api_context: tuple[AsyncClient, Any]) -> None:
        """缺必填字段应返回 422。"""
        client, _ = api_context
        resp = await client.post("/api/v1/meter/instruments", json={"asset_number": "A-1"})
        assert resp.status_code == 422


class TestListInstruments:
    async def test_paginated_list(self, api_context: tuple[AsyncClient, Any]) -> None:
        """列表应返回分页 meta 与数据数组。"""
        client, db = api_context
        dept = f"TEST-API-{uuid4().hex[:8]}"
        await create_instrument(db, department=dept)
        resp = await client.get(
            "/api/v1/meter/instruments", params={"department": dept}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["department"] == dept

    async def test_filter_options_include_overdue(self, api_context: tuple[AsyncClient, Any]) -> None:
        """筛选选项应包含动态状态"超期"且排在第一位。"""
        client, _ = api_context
        resp = await client.get("/api/v1/meter/instruments/filter-options")
        assert resp.status_code == 200
        statuses = resp.json()["data"]["status"]
        assert "超期" in statuses
        assert statuses[0] == "超期"


class TestGetInstrument:
    async def test_get_detail(self, api_context: tuple[AsyncClient, Any]) -> None:
        """详情应返回记录与 reports 数组。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.get(f"/api/v1/meter/instruments/{inst.id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == str(inst.id)
        assert data["reports"] == []

    async def test_get_missing_returns_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """不存在的器具应返回 404。"""
        client, _ = api_context
        resp = await client.get(f"/api/v1/meter/instruments/{uuid4()}")
        assert resp.status_code == 404


class TestUpdateInstrument:
    async def test_update_success(self, api_context: tuple[AsyncClient, Any]) -> None:
        """更新应返回修改后的字段。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.put(
            f"/api/v1/meter/instruments/{inst.id}", json={"location": "三车间"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["location"] == "三车间"

    async def test_update_missing_returns_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """更新不存在的器具应返回 404。"""
        client, _ = api_context
        resp = await client.put(
            f"/api/v1/meter/instruments/{uuid4()}", json={"location": "x"}
        )
        assert resp.status_code == 404


class TestDeleteInstrument:
    async def test_delete_then_get_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """软删除后详情应返回 404。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.delete(f"/api/v1/meter/instruments/{inst.id}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/v1/meter/instruments/{inst.id}")
        assert resp.status_code == 404

    async def test_batch_delete(self, api_context: tuple[AsyncClient, Any]) -> None:
        """批量删除应返回删除数量。"""
        client, db = api_context
        a = await create_instrument(db)
        b = await create_instrument(db)
        resp = await client.post(
            "/api/v1/meter/instruments/batch-delete",
            json={"ids": [str(a.id), str(b.id)]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted_count"] == 2


class TestGetInstrumentIds:
    async def test_ids_endpoint_returns_all_ids(self, api_context: tuple[AsyncClient, Any]) -> None:
        """筛选条件下所有 ID 应可通过 /instruments/ids 获取（跨页全选）。"""
        client, db = api_context
        dept = f"TEST-API-{uuid4().hex[:8]}"
        a = await create_instrument(db, department=dept)
        b = await create_instrument(db, department=dept)
        resp = await client.get(
            "/api/v1/meter/instruments/ids", params={"department": dept}
        )
        assert resp.status_code == 200
        ids = set(resp.json()["data"])
        assert ids == {str(a.id), str(b.id)}


class TestExportInstruments:
    async def test_export_csv(self, api_context: tuple[AsyncClient, Any]) -> None:
        """导出 CSV 应包含表头与 text/csv 类型。"""
        client, db = api_context
        await create_instrument(db)
        resp = await client.get("/api/v1/meter/instruments/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "资产编号" in resp.text

    async def test_export_excel(self, api_context: tuple[AsyncClient, Any]) -> None:
        """导出 Excel 应为 spreadsheetml 类型。"""
        client, db = api_context
        await create_instrument(db)
        resp = await client.get("/api/v1/meter/instruments/export-excel")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]


class TestBatchCreateAPI:
    async def test_batch_create(self, client_with_noop_commit: AsyncClient) -> None:
        """批量新增应返回 created/skipped 统计。"""
        resp = await client_with_noop_commit.post(
            "/api/v1/meter/instruments/batch",
            json={
                "items": [
                    {"asset_number": f"B-{uuid4().hex[:8]}", "instrument_name": "批量表1", "department": "质量部"},
                    {"asset_number": f"B-{uuid4().hex[:8]}", "instrument_name": "批量表2", "department": "质量部"},
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["total"] == 2
        assert body["created"] == 2
        assert body["skipped"] == 0


class TestInstrumentDepartmentsEndpoint:
    async def test_list_departments(self, api_context: tuple[AsyncClient, Any]) -> None:
        """/departments/instruments 应返回 instrument 来源部门列表。"""
        client, db = api_context
        from tests.modules.meter.conftest import create_department

        name = f"TEST-API-{uuid4().hex[:8]}"
        await create_department(db, source="instrument", name=name)
        resp = await client.get("/api/v1/meter/departments/instruments")
        assert resp.status_code == 200
        assert name in resp.json()["data"]


class TestInstrumentFilterLikeAndTypeahead:
    async def test_list_by_manufacturer_like(self, api_context: tuple[AsyncClient, Any]) -> None:
        """按 manufacturer_like（部分匹配）应筛出包含关键词的记录。"""
        client, db = api_context
        mfr = f"上岭{uuid4().hex[:4]}"
        await create_instrument(db, asset_number=f"AL-{uuid4().hex[:6]}", manufacturer=mfr, instrument_name="压力表")
        resp = await client.get("/api/v1/meter/instruments", params={"manufacturer_like": "上岭"})
        assert resp.status_code == 200
        body = resp.json()
        # 命中至少包含「上岭」的记录
        assert any("上岭" in (i.get("manufacturer") or "") for i in body["data"])
        assert body["meta"]["total"] >= 1

    async def test_typeahead_search_manufacturer(self, api_context: tuple[AsyncClient, Any]) -> None:
        """typeahead：按字段 + 关键字返回 distinct 命中值。"""
        client, db = api_context
        await create_instrument(db, asset_number=f"TA-{uuid4().hex[:6]}", manufacturer="上岭仪表", instrument_name="表")
        resp = await client.get(
            "/api/v1/meter/instruments/filter-options/search",
            params={"field": "manufacturer", "q": "上岭"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert any("上岭" in v for v in data["items"])

    async def test_typeahead_empty_q_returns_capped(self, api_context: tuple[AsyncClient, Any]) -> None:
        """typeahead：空 q 返回前 limit 个 distinct 值。"""
        client, db = api_context
        await create_instrument(db, asset_number=f"TB-{uuid4().hex[:6]}", manufacturer="测试制造商A", instrument_name="表")
        resp = await client.get(
            "/api/v1/meter/instruments/filter-options/search",
            params={"field": "manufacturer", "limit": 5},
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) <= 5

    async def test_typeahead_invalid_field_returns_400(self, api_context: tuple[AsyncClient, Any]) -> None:
        """typeahead：非法字段应返回 400。"""
        client, _ = api_context
        resp = await client.get(
            "/api/v1/meter/instruments/filter-options/search",
            params={"field": "__hack__"},
        )
        assert resp.status_code == 400

    async def test_typeahead_status_merges_overdue(self, api_context: tuple[AsyncClient, Any]) -> None:
        """typeahead：status 应并入动态计算的「超期」。"""
        client, _ = api_context
        resp = await client.get(
            "/api/v1/meter/instruments/filter-options/search",
            params={"field": "status", "q": "超"},
        )
        assert resp.status_code == 200
        assert "超期" in resp.json()["data"]["items"]

    async def test_keyword_hits_manufacturer(self, api_context: tuple[AsyncClient, Any]) -> None:
        """全局 keyword 应能命中制造商字段。"""
        client, db = api_context
        mfr = f"KW制造商{uuid4().hex[:4]}"
        await create_instrument(db, asset_number=f"KW-{uuid4().hex[:6]}", manufacturer=mfr, instrument_name="压力表")
        resp = await client.get("/api/v1/meter/instruments", params={"keyword": mfr})
        assert resp.status_code == 200
        assert any("KW制造商" in (i.get("manufacturer") or "") for i in resp.json()["data"])
