from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.energy import service
from app.modules.energy.schemas import (
    CollectTriggerRequest,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
)


@pytest.mark.asyncio
async def test_create_device_config_service(db_session, sample_device_config_data):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    obj = await service.create_device_config(db_session, data)
    assert obj.platform_code == "platform_a"


@pytest.mark.asyncio
async def test_create_duplicate_raises(db_session, sample_device_config_data):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    await service.create_device_config(db_session, data)

    with pytest.raises(DuplicateException):
        await service.create_device_config(db_session, data)


@pytest.mark.asyncio
async def test_get_device_config_not_found(db_session):
    with pytest.raises(NotFoundException):
        await service.get_device_config(db_session, uuid4())


@pytest.mark.asyncio
async def test_update_device_config_service(db_session, sample_device_config_data):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    created = await service.create_device_config(db_session, data)

    update = EnergyDeviceConfigUpdate(device_name="更新后的名称")
    updated = await service.update_device_config(db_session, created.id, update)
    assert updated.device_name == "更新后的名称"


@pytest.mark.asyncio
async def test_delete_device_config_service(db_session, sample_device_config_data):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    created = await service.create_device_config(db_session, data)
    await service.delete_device_config(db_session, created.id)

    with pytest.raises(NotFoundException):
        await service.get_device_config(db_session, created.id)


@pytest.mark.asyncio
async def test_trigger_collection_no_devices(db_session):
    request = CollectTriggerRequest(platform_code="platform_a")
    result = await service.trigger_collection(db_session, request)
    assert result["platform_a"]["status"] == "success"
    assert result["platform_a"]["device_count"] == 0


@pytest.mark.asyncio
async def test_trigger_collection_unknown_platform(db_session):
    request = CollectTriggerRequest(platform_code="unknown")
    result = await service.trigger_collection(db_session, request)
    assert result["unknown"]["status"] == "failed"
