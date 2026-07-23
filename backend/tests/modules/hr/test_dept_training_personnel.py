"""部门培训人员 — API 测试。

覆盖列表查询和 CRUD。
"""

import pytest

from tests.modules.hr.conftest import _rand


@pytest.mark.asyncio
async def test_api_list_dept_training_personnel(client):
    """GET /dept-training-personnel 返回 200。"""
    resp = await client.get("/api/v1/hr/dept-training-personnel?page=1&page_size=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_dept_training_personnel(client):
    """POST 新增部门培训人员返回 201。"""
    resp = await client.post("/api/v1/hr/dept-training-personnel", json={
        "display_department": _rand("部门"),
        "department": _rand("部门"),
        "training_admin": "管理员A",
        "department_head": "负责人A",
        "level1_trainer": "培训师A",
    })
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "id" in data


@pytest.mark.asyncio
async def test_api_delete_dept_training_personnel(client):
    """DELETE 返回 200。"""
    resp = await client.post("/api/v1/hr/dept-training-personnel", json={
        "display_department": _rand("删除部门"),
        "department": _rand("删除部门"),
    })
    item_id = resp.json()["data"]["id"]

    resp2 = await client.delete(f"/api/v1/hr/dept-training-personnel/{item_id}")
    assert resp2.status_code == 200
