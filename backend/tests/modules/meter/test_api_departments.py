"""部门管理 API 端点功能测试。

契约：source 限定 instrument/gas_detector；改名联动；有记录部门不可删除（409）；
负责人候选人来自 identity.users。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.modules.meter.conftest import create_department, create_instrument


class TestDepartmentCrud:
    async def test_create_department(self, api_context: tuple[AsyncClient, Any]) -> None:
        """新增部门应返回 201。"""
        client, _ = api_context
        name = f"TEST-API-{uuid4().hex[:8]}"
        resp = await client.post(
            "/api/v1/meter/departments",
            json={"source": "instrument", "name": name, "heads": [{"name": "张三", "feishu_open_id": "ou_1"}]},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["name"] == name

    async def test_create_invalid_source_returns_422(self, api_context: tuple[AsyncClient, Any]) -> None:
        """非法 source 应被 schema 拒绝返回 422。"""
        client, _ = api_context
        resp = await client.post(
            "/api/v1/meter/departments",
            json={"source": "other", "name": "部门X"},
        )
        assert resp.status_code == 422

    async def test_list_departments(self, api_context: tuple[AsyncClient, Any]) -> None:
        """部门列表应返回 record_count。"""
        client, db = api_context
        name = f"TEST-API-{uuid4().hex[:8]}"
        await create_department(db, source="instrument", name=name)
        await create_instrument(db, department=name)
        resp = await client.get(
            "/api/v1/meter/departments", params={"source": "instrument"}
        )
        assert resp.status_code == 200
        target = [d for d in resp.json()["data"] if d["name"] == name]
        assert len(target) == 1
        assert target[0]["record_count"] == 1

    async def test_update_rename(self, api_context: tuple[AsyncClient, Any]) -> None:
        """改名应联动更新记录。"""
        client, db = api_context
        old_name = f"TEST-OLD-{uuid4().hex[:8]}"
        new_name = f"TEST-NEW-{uuid4().hex[:8]}"
        dept = await create_department(db, source="instrument", name=old_name)
        inst = await create_instrument(db, department=old_name)
        resp = await client.put(
            f"/api/v1/meter/departments/{dept.id}", json={"name": new_name}
        )
        assert resp.status_code == 200
        detail = await client.get(f"/api/v1/meter/instruments/{inst.id}")
        assert detail.json()["data"]["department"] == new_name

    async def test_toggle_auto_notify(self, api_context: tuple[AsyncClient, Any]) -> None:
        """切换自动提醒开关应返回新状态。"""
        client, db = api_context
        dept = await create_department(db, auto_notify_enabled=False)
        resp = await client.put(f"/api/v1/meter/departments/{dept.id}/auto-notify")
        assert resp.status_code == 200
        assert resp.json()["data"]["auto_notify_enabled"] is True

    async def test_delete_with_records_returns_409(self, api_context: tuple[AsyncClient, Any]) -> None:
        """有记录使用的部门不可删除，应返回 409。"""
        client, db = api_context
        name = f"TEST-API-{uuid4().hex[:8]}"
        dept = await create_department(db, source="instrument", name=name)
        await create_instrument(db, department=name)
        resp = await client.delete(f"/api/v1/meter/departments/{dept.id}")
        assert resp.status_code == 409

    async def test_delete_empty_department(self, api_context: tuple[AsyncClient, Any]) -> None:
        """无记录使用的部门可删除。"""
        client, db = api_context
        dept = await create_department(db)
        resp = await client.delete(f"/api/v1/meter/departments/{dept.id}")
        assert resp.status_code == 200


class TestPersonnelCandidates:
    async def test_candidates_from_identity(self, api_context: tuple[AsyncClient, Any]) -> None:
        """候选人列表应来自 identity.users。"""
        client, db = api_context
        from app.platform.identity.models import User

        marker = uuid4().hex[:8]
        db.add(User(name=f"候选人{marker}", feishu_open_id=f"ou_{marker}"))
        await db.flush()
        resp = await client.get("/api/v1/meter/departments/personnel-candidates")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()["data"]]
        assert f"候选人{marker}" in names
