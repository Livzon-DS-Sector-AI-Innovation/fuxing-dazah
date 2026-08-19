from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.energy import service
from app.modules.energy.models import EnergyData, EnergyDeviceConfig
from app.modules.energy.schemas import (
    CollectTriggerRequest,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
)


@pytest.mark.asyncio
async def test_create_device_config_service(db_session, sample_device_config_data, water_energy_type_config):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    obj = await service.create_device_config(db_session, data)
    assert obj.platform_code == "zhiheng"


@pytest.mark.asyncio
async def test_create_duplicate_raises(db_session, sample_device_config_data, water_energy_type_config):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    await service.create_device_config(db_session, data)

    with pytest.raises(DuplicateException):
        await service.create_device_config(db_session, data)


@pytest.mark.asyncio
async def test_get_device_config_not_found(db_session):
    with pytest.raises(NotFoundException):
        await service.get_device_config(db_session, uuid4())


@pytest.mark.asyncio
async def test_update_device_config_service(db_session, sample_device_config_data, water_energy_type_config):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    created = await service.create_device_config(db_session, data)

    update = EnergyDeviceConfigUpdate(device_name="更新后的名称")
    updated = await service.update_device_config(db_session, created.id, update)
    assert updated.device_name == "更新后的名称"


@pytest.mark.asyncio
async def test_delete_device_config_service(db_session, sample_device_config_data, water_energy_type_config):
    data = EnergyDeviceConfigCreate(**sample_device_config_data)
    created = await service.create_device_config(db_session, data)
    await service.delete_device_config(db_session, created.id)

    with pytest.raises(NotFoundException):
        await service.get_device_config(db_session, created.id)


@pytest.mark.asyncio
async def test_trigger_collection_no_devices(db_session):
    request = CollectTriggerRequest(platform_code="zhiheng")
    result = await service.trigger_collection(db_session, request)
    assert result["zhiheng"]["status"] == "success"
    assert result["zhiheng"]["device_count"] == 0


@pytest.mark.asyncio
async def test_trigger_collection_unknown_platform(db_session):
    request = CollectTriggerRequest(platform_code="unknown")
    result = await service.trigger_collection(db_session, request)
    assert result["unknown"]["status"] == "failed"


@pytest.mark.asyncio
async def test_collect_settings_time_roundtrip(db_session):
    """每日采集时间配置后应持久化到 DB，重启后仍可读回（而非写死 08:00）。"""
    await service.update_collect_settings(db_session, daily_collect_time="09:30")
    result = await service.get_collect_settings(db_session)
    assert result["daily_collect_time"] == "09:30"
    assert isinstance(result["auto_collect_enabled"], bool)


def _make_device(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "platform_code": "zhiheng",
        "platform_device_code": "DEV-X",
        "device_name": "设备",
        "energy_type": "electricity",
        "api_endpoint": "/api/v1/electricity/hourly",
        "workshop": "车间A",
        "unit": "kWh",
        "monitor_level": "normal",
        "is_enabled": True,
        "is_region_level": False,
        "stat_role": "normal",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_price_category_prefers_region_total(db_session):
    """峰谷分布「总耗」模式：存在区域级总耗设备时只用其值，不叠加 normal 子表。"""
    total_dev = EnergyDeviceConfig(
        **_make_device(
            platform_device_code="TOTAL-METER",
            device_name="全厂总电表",
            workshop="全厂",
            is_region_level=True,
            stat_role="total",
        )
    )
    normal_dev = EnergyDeviceConfig(
        **_make_device(
            platform_device_code="SUB-METER-1",
            device_name="车间A子表",
            stat_role="normal",
        )
    )
    db_session.add_all([total_dev, normal_dev])
    await db_session.flush()

    ts = datetime(2026, 8, 18, 2, 0, 0, tzinfo=UTC)  # 10:00 CST
    db_session.add_all([
        EnergyData(device_config_id=total_dev.id, timestamp=ts, value=Decimal("100"), unit="kWh"),
        EnergyData(device_config_id=normal_dev.id, timestamp=ts, value=Decimal("30"), unit="kWh"),
    ])
    await db_session.flush()

    result = await service.get_price_category_distribution(
        db_session, ts - timedelta(hours=1), ts + timedelta(hours=1)
    )
    # 总耗应等于总耗设备的值（100），而非总耗+子表（130）
    assert result["total"] == 100.0
