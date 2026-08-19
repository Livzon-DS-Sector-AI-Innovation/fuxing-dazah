from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.energy import repository as repo
from app.modules.energy.collect_settings import CST


@pytest.mark.asyncio
async def test_create_and_get_device_config(db_session, sample_device_config_data):
    created = await repo.create_device_config(db_session, sample_device_config_data)
    assert created.id is not None
    assert created.platform_code == "zhiheng"

    fetched = await repo.get_device_config_by_id(db_session, created.id)
    assert fetched is not None
    assert fetched.platform_device_code == "WD-001"


@pytest.mark.asyncio
async def test_list_device_configs_with_filters(db_session, sample_device_config_data):
    await repo.create_device_config(db_session, sample_device_config_data)

    other = {
        **sample_device_config_data,
        "platform_device_code": "WD-002",
        "workshop": "合成车间",
    }
    await repo.create_device_config(db_session, other)

    items, total = await repo.list_device_configs(db_session, workshop="发酵车间")
    assert total == 1
    assert items[0].workshop == "发酵车间"


@pytest.mark.asyncio
async def test_update_device_config(db_session, sample_device_config_data):
    created = await repo.create_device_config(db_session, sample_device_config_data)
    updated = await repo.update_device_config(
        db_session, created.id, {"device_name": "新名称"}
    )
    assert updated.device_name == "新名称"


@pytest.mark.asyncio
async def test_soft_delete_device_config(db_session, sample_device_config_data):
    created = await repo.create_device_config(db_session, sample_device_config_data)
    result = await repo.delete_device_config(db_session, created.id)
    assert result is True

    fetched = await repo.get_device_config_by_id(db_session, created.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_exists_device_config(db_session, sample_device_config_data):
    await repo.create_device_config(db_session, sample_device_config_data)
    exists = await repo.exists_device_config(db_session, "zhiheng", "WD-001")
    assert exists is True

    not_exists = await repo.exists_device_config(db_session, "zhiheng", "WD-999")
    assert not_exists is False


@pytest.mark.asyncio
async def test_exists_device_config_exclude_id(db_session, sample_device_config_data):
    created = await repo.create_device_config(db_session, sample_device_config_data)
    exists = await repo.exists_device_config(
        db_session, "zhiheng", "WD-001", exclude_id=created.id
    )
    assert exists is False


@pytest.mark.asyncio
async def test_upsert_energy_data(db_session, sample_device_config_data):
    config = await repo.create_device_config(db_session, sample_device_config_data)
    config_id = config.id
    ts = datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)

    data = await repo.upsert_energy_data(
        db_session, device_config_id=config_id, timestamp=ts, value=100.0, unit="m3"
    )
    assert float(data.value) == 100.0

    # Clear the identity map so the second upsert RETURNING reads fresh
    # values instead of returning the cached identity-map entry.
    # We use config_id (a plain UUID) so no ORM lazy-load is triggered.
    db_session.expire_all()

    data2 = await repo.upsert_energy_data(
        db_session, device_config_id=config_id, timestamp=ts, value=150.0, unit="m3"
    )
    assert float(data2.value) == 150.0


@pytest.mark.asyncio
async def test_get_enabled_devices_by_platform(db_session, sample_device_config_data):
    await repo.create_device_config(db_session, sample_device_config_data)

    disabled = {
        **sample_device_config_data,
        "platform_device_code": "WD-003",
        "is_enabled": False,
    }
    await repo.create_device_config(db_session, disabled)

    devices = await repo.get_enabled_devices_by_platform(db_session, "zhiheng")
    assert len(devices) == 1
    assert devices[0].is_enabled is True


@pytest.mark.asyncio
async def test_get_platform_backfill_start_day_with_gap(
    db_session, sample_device_config_data
):
    config = await repo.create_device_config(db_session, sample_device_config_data)
    # 最近一条数据落在 8 月 15 日，昨天为 8 月 18 日 → 应从 16 日开始回溯
    await repo.upsert_energy_data(
        db_session,
        device_config_id=config.id,
        timestamp=datetime(2026, 8, 15, 8, 0, tzinfo=CST),
        value=1.0,
        unit="m3",
    )
    start = await repo.get_platform_backfill_start_day(
        db_session, "zhiheng", date(2026, 8, 18)
    )
    assert start == date(2026, 8, 16)


@pytest.mark.asyncio
async def test_get_platform_backfill_start_day_no_data_uses_device_created(
    db_session, sample_device_config_data
):
    # 无任何数据：回溯下限为最早启用设备的创建日
    await repo.create_device_config(
        db_session,
        {
            **sample_device_config_data,
            "created_at": datetime(2026, 8, 1, 0, 0, tzinfo=CST),
        },
    )
    start = await repo.get_platform_backfill_start_day(
        db_session, "zhiheng", date(2026, 8, 18)
    )
    assert start == date(2026, 8, 1)


@pytest.mark.asyncio
async def test_get_platform_backfill_start_day_up_to_date(
    db_session, sample_device_config_data
):
    config = await repo.create_device_config(db_session, sample_device_config_data)
    await repo.upsert_energy_data(
        db_session,
        device_config_id=config.id,
        timestamp=datetime(2026, 8, 18, 8, 0, tzinfo=CST),
        value=1.0,
        unit="m3",
    )
    # 已补齐到昨天：仍返回昨天（幂等采集，保证每日都写采集日志）
    start = await repo.get_platform_backfill_start_day(
        db_session, "zhiheng", date(2026, 8, 18)
    )
    assert start == date(2026, 8, 18)


@pytest.mark.asyncio
async def test_get_platform_backfill_start_day_future_data_clamped(
    db_session, sample_device_config_data
):
    config = await repo.create_device_config(db_session, sample_device_config_data)
    await repo.upsert_energy_data(
        db_session,
        device_config_id=config.id,
        timestamp=datetime(2026, 8, 19, 8, 0, tzinfo=CST),
        value=1.0,
        unit="m3",
    )
    # 数据日期晚于昨天（异常/时钟偏差）：回溯起点不回退，仍返回昨天
    start = await repo.get_platform_backfill_start_day(
        db_session, "zhiheng", date(2026, 8, 18)
    )
    assert start == date(2026, 8, 18)
