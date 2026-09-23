from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException


@pytest.mark.asyncio
async def test_create_device_config_api(client, sample_device_config_data):
    response = await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["platform_code"] == "zhiheng"


@pytest.mark.asyncio
async def test_list_device_configs_api(client, sample_device_config_data):
    await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )

    response = await client.get(
        "/api/v1/energy/devices?platform_code=zhiheng"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] >= 1


@pytest.mark.asyncio
async def test_get_device_config_api(client, sample_device_config_data):
    create_resp = await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )
    config_id = create_resp.json()["data"]["id"]

    response = await client.get(f"/api/v1/energy/devices/{config_id}")
    assert response.status_code == 200
    assert response.json()["data"]["id"] == config_id


@pytest.mark.asyncio
async def test_update_device_config_api(client, sample_device_config_data):
    create_resp = await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )
    config_id = create_resp.json()["data"]["id"]

    response = await client.put(
        f"/api/v1/energy/devices/{config_id}",
        json={"device_name": "新名称"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["device_name"] == "新名称"


@pytest.mark.asyncio
async def test_delete_device_config_api(client, sample_device_config_data):
    create_resp = await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )
    config_id = create_resp.json()["data"]["id"]

    response = await client.delete(f"/api/v1/energy/devices/{config_id}")
    assert response.status_code == 200

    get_resp = await client.get(f"/api/v1/energy/devices/{config_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_trigger_collection_api(client):
    response = await client.post(
        "/api/v1/energy/collect/trigger",
        json={"platform_code": "zhiheng"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_collect_logs_api(client):
    response = await client.get("/api/v1/energy/collect/logs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_equipment_options_api_includes_shared_reference(client):
    equipment_id = uuid4()
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-SHARED",
        name="共享设备",
        status="在用",
        is_active=True,
    )
    with patch(
        "app.modules.equipment.public_api.list_equipment_references",
        new=AsyncMock(return_value=([reference], 1)),
    ) as list_refs:
        response = await client.get(
            "/api/v1/energy/equipment-options?keyword=共享"
        )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": str(equipment_id),
            "equipment_no": "EQ-SHARED",
            "name": "共享设备",
            "status": "在用",
            "is_active": True,
        }
    ]
    list_refs.assert_awaited_once()


@pytest.mark.asyncio
async def test_equipment_options_api_id_echo_is_scoped(client):
    equipment_id = uuid4()
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-RECALL",
        name="回显设备",
        status="在用",
        is_active=True,
    )
    with patch(
        "app.modules.equipment.public_api.get_equipment_references_by_ids",
        new=AsyncMock(return_value=[reference]),
    ) as get_refs:
        response = await client.get(
            f"/api/v1/energy/equipment-options?ids={equipment_id}"
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["name"] == "回显设备"
    get_refs.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_device_config_api_rejects_unshared_equipment(
    client,
    sample_device_config_data,
):
    equipment_id = uuid4()
    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(side_effect=ForbiddenException("设备不可用或无权关联")),
    ):
        response = await client.post(
            "/api/v1/energy/devices",
            json={
                **sample_device_config_data,
                "equipment_ids": [str(equipment_id)],
                "equipment_names": ["伪造名称"],
            },
        )

    assert response.status_code == 403
    assert "无权关联" in response.json()["message"]


@pytest.mark.asyncio
async def test_update_device_config_api_rebuilds_equipment_names(
    client,
    sample_device_config_data,
):
    create_resp = await client.post(
        "/api/v1/energy/devices", json=sample_device_config_data
    )
    config_id = create_resp.json()["data"]["id"]
    equipment_id = uuid4()
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-AUTH",
        name="授权设备",
        status="在用",
        is_active=True,
    )
    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(return_value=[reference]),
    ):
        response = await client.put(
            f"/api/v1/energy/devices/{config_id}",
            json={
                "equipment_ids": [str(equipment_id)],
                "equipment_names": ["客户端伪造"],
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["equipment_ids"] == [str(equipment_id)]
    assert response.json()["data"]["equipment_names"] == ["授权设备"]
