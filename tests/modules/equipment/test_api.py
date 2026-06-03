"""Equipment API integration tests."""

import uuid

from httpx import AsyncClient


def _uid() -> str:
    """Generate a short unique suffix for test data codes."""
    return uuid.uuid4().hex[:6].upper()


async def test_create_equipment_category(client: AsyncClient):
    """测试创建设备分类"""
    code = f"RF-{_uid()}"
    response = await client.post(
        "/api/v1/equipment/categories",
        json={
            "name": "反应釜",
            "code": code,
            "description": "反应设备",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["data"]["name"] == "反应釜"
    assert data["data"]["code"] == code


async def test_get_equipment_categories(client: AsyncClient):
    """测试获取设备分类列表"""
    uid = _uid()
    await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": f"RF-{uid}"},
    )
    await client.post(
        "/api/v1/equipment/categories",
        json={"name": "离心机", "code": f"LXJ-{uid}"},
    )

    response = await client.get("/api/v1/equipment/categories")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert len(data["data"]) >= 2


async def test_get_equipment_category_by_id(client: AsyncClient):
    """测试根据ID获取设备分类"""
    code = f"RF-{_uid()}"
    create_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": code},
    )
    category_id = create_response.json()["data"]["id"]

    response = await client.get(f"/api/v1/equipment/categories/{category_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["name"] == "反应釜"


async def test_update_equipment_category(client: AsyncClient):
    """测试更新设备分类"""
    code = f"RF-{_uid()}"
    create_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": code},
    )
    category_id = create_response.json()["data"]["id"]

    response = await client.put(
        f"/api/v1/equipment/categories/{category_id}",
        json={"name": "大型反应釜"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["name"] == "大型反应釜"


async def test_delete_equipment_category(client: AsyncClient):
    """测试删除设备分类"""
    code = f"RF-{_uid()}"
    create_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": code},
    )
    category_id = create_response.json()["data"]["id"]

    response = await client.delete(f"/api/v1/equipment/categories/{category_id}")
    assert response.status_code == 200


async def test_create_location(client: AsyncClient):
    """测试创建位置"""
    code = f"WS-{_uid()}"
    response = await client.post(
        "/api/v1/equipment/locations",
        json={
            "name": "一车间",
            "code": code,
            "description": "一车间位置",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["name"] == "一车间"


async def test_create_equipment(client: AsyncClient):
    """测试创建设备"""
    uid = _uid()
    cat_code = f"RF-{uid}"
    loc_code = f"WS-{uid}"

    # 先创建分类和位置
    category_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": cat_code},
    )
    category_id = category_response.json()["data"]["id"]

    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "一车间", "code": loc_code},
    )
    location_id = location_response.json()["data"]["id"]

    # 创建设备
    response = await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "R-101反应釜",
            "category_id": category_id,
            "location_id": location_id,
            "status": "在用",
            "model": "RF-1000",
            "manufacturer": "某设备厂",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["equipment_no"] == f"EQ-{cat_code}-0001"
    assert data["data"]["name"] == "R-101反应釜"


async def test_get_equipments(client: AsyncClient):
    """测试获取设备列表"""
    uid = _uid()
    cat_code = f"RF-{uid}"
    loc_code = f"WS-{uid}"

    # 先创建分类和位置
    category_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": cat_code},
    )
    category_id = category_response.json()["data"]["id"]

    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "一车间", "code": loc_code},
    )
    location_id = location_response.json()["data"]["id"]

    # 创建多个设备
    await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "R-101反应釜",
            "category_id": category_id,
            "location_id": location_id,
        },
    )
    await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "R-102反应釜",
            "category_id": category_id,
            "location_id": location_id,
        },
    )

    response = await client.get("/api/v1/equipment/equipments")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert len(data["data"]) >= 2


async def test_get_equipment_statistics(client: AsyncClient):
    """测试获取设备统计"""
    response = await client.get("/api/v1/equipment/equipments/statistics")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data["data"]
    assert "by_status" in data["data"]
