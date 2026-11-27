from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.energy import service
from app.modules.energy.models import EnergyData, EnergyDeviceConfig
from app.modules.energy.schemas import (
    CollectTriggerRequest,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
)
from app.platform.identity.models import User


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
async def test_create_device_config_revalidates_equipment_and_rebuilds_names(
    db_session,
    sample_device_config_data,
    water_energy_type_config,
):
    """客户端传入的 equipment_names 不能绕过设备引用授权。"""
    equipment_id = uuid4()
    sample_device_config_data = {
        **sample_device_config_data,
        "equipment_ids": [str(equipment_id), str(equipment_id)],
        "equipment_names": ["伪造名称"],
    }
    user = User(name="能源测试用户", employee_no=f"ENERGY-{uuid4().hex[:8]}")
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-001",
        name="真实设备名称",
        status="在用",
        is_active=True,
    )
    data = EnergyDeviceConfigCreate(**sample_device_config_data)

    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(return_value=[reference]),
    ) as validate:
        obj = await service.create_device_config(db_session, data, user)

    assert obj.equipment_ids == [str(equipment_id)]
    assert obj.equipment_names == ["真实设备名称"]
    validate.assert_awaited_once_with(
        db_session,
        user,
        "energy",
        [equipment_id],
        auto_publish_owned=True,
    )


@pytest.mark.asyncio
async def test_update_device_config_revalidates_equipment_and_rebuilds_names(
    db_session,
    sample_device_config_data,
    water_energy_type_config,
):
    created = await service.create_device_config(
        db_session,
        EnergyDeviceConfigCreate(**sample_device_config_data),
    )
    equipment_id = uuid4()
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-002",
        name="更新后的真实设备",
        status="在用",
        is_active=True,
    )
    user = User(name="能源测试用户", employee_no=f"ENERGY-{uuid4().hex[:8]}")

    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(return_value=[reference]),
    ) as validate:
        updated = await service.update_device_config(
            db_session,
            created.id,
            EnergyDeviceConfigUpdate(
                equipment_ids=[str(equipment_id)],
                equipment_names=["客户端伪造"],
            ),
            user,
        )

    assert updated.equipment_ids == [str(equipment_id)]
    assert updated.equipment_names == ["更新后的真实设备"]
    validate.assert_awaited_once_with(
        db_session,
        user,
        "energy",
        [equipment_id],
        auto_publish_owned=True,
    )


@pytest.mark.asyncio
async def test_update_device_config_ignores_names_only_input(
    db_session,
    sample_device_config_data,
    water_energy_type_config,
):
    equipment_id = uuid4()
    reference = SimpleNamespace(
        id=equipment_id,
        equipment_no="EQ-HISTORY",
        name="历史名称",
        status="在用",
        is_active=True,
    )
    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(return_value=[reference]),
    ):
        created = await service.create_device_config(
            db_session,
            EnergyDeviceConfigCreate(
                **{
                    **sample_device_config_data,
                    "equipment_ids": [str(equipment_id)],
                    "equipment_names": ["客户端伪造"],
                }
            ),
        )

    updated = await service.update_device_config(
        db_session,
        created.id,
        EnergyDeviceConfigUpdate(equipment_names=["客户端伪造"]),
    )

    assert updated.equipment_names == ["历史名称"]


@pytest.mark.asyncio
async def test_create_device_config_rejects_revoked_equipment(
    db_session,
    sample_device_config_data,
    water_energy_type_config,
):
    equipment_id = uuid4()
    data = EnergyDeviceConfigCreate(
        **{
            **sample_device_config_data,
            "equipment_ids": [str(equipment_id)],
            "equipment_names": ["已撤销设备"],
        }
    )
    user = User(name="能源测试用户", employee_no=f"ENERGY-{uuid4().hex[:8]}")

    with patch(
        "app.modules.equipment.public_api.validate_equipment_references",
        new=AsyncMock(side_effect=ForbiddenException("设备不可用或无权关联")),
    ):
        with pytest.raises(ForbiddenException, match="无权关联"):
            await service.create_device_config(db_session, data, user)


@pytest.mark.asyncio
async def test_list_equipment_options_uses_energy_reference_scope(db_session):
    user = User(name="能源测试用户", employee_no=f"ENERGY-{uuid4().hex[:8]}")
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
        options = await service.list_equipment_options(
            db_session,
            user,
            keyword="共享",
            page_size=10,
        )

    assert options == [
        {
            "id": str(equipment_id),
            "equipment_no": "EQ-SHARED",
            "name": "共享设备",
            "status": "在用",
            "is_active": True,
        }
    ]
    list_refs.assert_awaited_once_with(
        db_session,
        user,
        "energy",
        keyword="共享",
        page=1,
        page_size=10,
    )


@pytest.mark.asyncio
async def test_get_equipment_options_by_ids_uses_reference_scope(db_session):
    user = User(name="能源测试用户", employee_no=f"ENERGY-{uuid4().hex[:8]}")
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
        options = await service.get_equipment_options_by_ids(
            db_session,
            user,
            [equipment_id],
        )

    assert options[0]["name"] == "回显设备"
    get_refs.assert_awaited_once_with(
        db_session,
        user,
        "energy",
        [equipment_id],
    )


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
