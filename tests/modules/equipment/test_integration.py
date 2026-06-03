"""Equipment module integration tests: lifecycle, numbering, and filtering."""

import uuid

from httpx import AsyncClient


def _uid() -> str:
    """Generate a short unique suffix for test data codes."""
    return uuid.uuid4().hex[:6].upper()


async def test_equipment_lifecycle(client: AsyncClient):
    """测试设备生命周期：创建分类 -> 创建位置 -> 创建设备 -> 更新设备 -> 删除设备"""
    uid = _uid()
    cat_code = f"RF-{uid}"
    loc_code = f"WS-{uid}"

    # 1. 创建设备分类
    category_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": cat_code, "description": "反应设备"},
    )
    assert category_response.status_code == 200
    category_id = category_response.json()["data"]["id"]

    # 2. 创建位置
    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "一车间", "code": loc_code, "description": "一车间位置"},
    )
    assert location_response.status_code == 200
    location_id = location_response.json()["data"]["id"]

    # 3. 创建设备
    equipment_response = await client.post(
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
    assert equipment_response.status_code == 200
    equipment_data = equipment_response.json()["data"]
    assert equipment_data["equipment_no"] == f"EQ-{cat_code}-0001"
    assert equipment_data["name"] == "R-101反应釜"
    equipment_id = equipment_data["id"]

    # 4. 更新设备状态
    update_response = await client.put(
        f"/api/v1/equipment/equipments/{equipment_id}",
        json={"status": "维修中"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["status"] == "维修中"

    # 5. 获取设备详情
    detail_response = await client.get(f"/api/v1/equipment/equipments/{equipment_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["status"] == "维修中"

    # 6. 删除设备
    equip_url = f"/api/v1/equipment/equipments/{equipment_id}"
    delete_response = await client.delete(equip_url)
    assert delete_response.status_code == 200

    # 7. 验证设备已被删除（软删除后返回404）
    detail_response = await client.get(equip_url)
    assert detail_response.status_code == 404


async def test_equipment_number_generation(client: AsyncClient):
    """测试设备编号自动生成"""
    uid = _uid()
    cat_code = f"LXJ-{uid}"
    loc_code = f"WS-{uid}"

    # 创建分类
    category_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "离心机", "code": cat_code},
    )
    assert category_response.status_code == 200
    category_id = category_response.json()["data"]["id"]

    # 创建位置
    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "二车间", "code": loc_code},
    )
    assert location_response.status_code == 200
    location_id = location_response.json()["data"]["id"]

    # 创建多个设备，验证编号递增
    for i in range(1, 4):
        response = await client.post(
            "/api/v1/equipment/equipments",
            json={
                "name": f"C-{i:03d}离心机",
                "category_id": category_id,
                "location_id": location_id,
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["equipment_no"] == f"EQ-{cat_code}-{i:04d}"


async def test_equipment_filter(client: AsyncClient):
    """测试设备筛选功能"""
    uid = _uid()
    cat_code = f"RF-{uid}"
    loc_code = f"WS-{uid}"

    # 创建分类和位置
    category_response = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "反应釜", "code": cat_code},
    )
    assert category_response.status_code == 200
    category_id = category_response.json()["data"]["id"]

    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "一车间", "code": loc_code},
    )
    assert location_response.status_code == 200
    location_id = location_response.json()["data"]["id"]

    # 创建不同状态的设备
    await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "R-101反应釜",
            "category_id": category_id,
            "location_id": location_id,
            "status": "在用",
        },
    )
    await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "R-102反应釜",
            "category_id": category_id,
            "location_id": location_id,
            "status": "备用",
        },
    )

    # 按状态筛选 - 使用 category_id 限定范围以精确断言
    response = await client.get(
        f"/api/v1/equipment/equipments?status=在用&category_id={category_id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] == 1
    assert len(data["data"]) == 1
    assert data["data"][0]["status"] == "在用"
    assert data["data"][0]["name"] == "R-101反应釜"

    # 按关键词搜索 - 使用 category_id 限定范围以精确断言
    response = await client.get(
        f"/api/v1/equipment/equipments?keyword=R-101&category_id={category_id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] == 1
    assert len(data["data"]) == 1
    assert "R-101" in data["data"][0]["name"]


async def test_create_equipment_with_nonexistent_category(client: AsyncClient):
    """测试使用不存在的分类ID创建设备（应返回404）"""
    uid = _uid()
    loc_code = f"WS-{uid}"

    # 创建一个有效的位置
    location_response = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "测试车间", "code": loc_code},
    )
    assert location_response.status_code == 200
    location_id = location_response.json()["data"]["id"]

    # 使用不存在的分类ID创建设备
    fake_category_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "测试设备",
            "category_id": fake_category_id,
            "location_id": location_id,
        },
    )
    assert response.status_code == 404


async def test_create_duplicate_category_code(client: AsyncClient):
    """测试创建重复的分类代码（应返回409）"""
    uid = _uid()
    cat_code = f"DUP-{uid}"

    # 创建第一个分类
    response1 = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "分类A", "code": cat_code},
    )
    assert response1.status_code == 200

    # 尝试创建相同代码的分类
    response2 = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "分类B", "code": cat_code},
    )
    assert response2.status_code == 409


async def test_get_nonexistent_equipment(client: AsyncClient):
    """测试获取不存在的设备（应返回404）"""
    fake_equipment_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/equipment/equipments/{fake_equipment_id}")
    assert response.status_code == 404
