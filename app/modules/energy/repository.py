"""Energy database queries and persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyData,
    EnergyDeviceConfig,
)

# ── 设备配置 ──


async def create_device_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyDeviceConfig:
    obj = EnergyDeviceConfig(**data)
    db.add(obj)
    await db.flush()
    return obj


async def get_device_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyDeviceConfig | None:
    result = await db.execute(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_device_configs(
    db: AsyncSession,
    *,
    platform_code: str | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    is_enabled: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyDeviceConfig], int]:
    query = select(EnergyDeviceConfig).where(
        EnergyDeviceConfig.is_deleted == False  # noqa: E712
    )
    if platform_code:
        query = query.where(EnergyDeviceConfig.platform_code == platform_code)
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)
    if workshop:
        query = query.where(EnergyDeviceConfig.workshop == workshop)
    if is_enabled is not None:
        query = query.where(EnergyDeviceConfig.is_enabled == is_enabled)
    if keyword:
        query = query.where(EnergyDeviceConfig.device_name.ilike(f"%{keyword}%"))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_device_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyDeviceConfig | None:
    obj = await get_device_config_by_id(db, config_id)
    if obj is None:
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()
    # Re-fetch via select to avoid MissingGreenlet (禁止 db.refresh)
    result = await db.execute(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def delete_device_config(db: AsyncSession, config_id: UUID) -> bool:
    obj = await get_device_config_by_id(db, config_id)
    if obj is None:
        return False
    obj.is_deleted = True
    await db.flush()
    return True


async def exists_device_config(
    db: AsyncSession,
    platform_code: str,
    platform_device_code: str,
    exclude_id: UUID | None = None,
) -> bool:
    query = select(func.count()).where(
        EnergyDeviceConfig.platform_code == platform_code,
        EnergyDeviceConfig.platform_device_code == platform_device_code,
        EnergyDeviceConfig.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(EnergyDeviceConfig.id != exclude_id)
    count = (await db.execute(query)).scalar() or 0
    return count > 0


async def get_enabled_devices_by_platform(
    db: AsyncSession, platform_code: str
) -> list[EnergyDeviceConfig]:
    result = await db.execute(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.platform_code == platform_code,
            EnergyDeviceConfig.is_enabled == True,  # noqa: E712
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_latest_energy_data(
    db: AsyncSession, device_config_id: UUID
) -> EnergyData | None:
    """获取指定设备最近一条能耗数据记录。"""
    result = await db.execute(
        select(EnergyData)
        .where(
            EnergyData.device_config_id == device_config_id,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_distinct_enabled_platforms(db: AsyncSession) -> list[str]:
    """返回所有有启用设备的平台 code 列表（去重）。"""
    result = await db.execute(
        select(EnergyDeviceConfig.platform_code)
        .where(
            EnergyDeviceConfig.is_enabled == True,  # noqa: E712
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )
    return list(result.scalars().all())


# ── 能耗数据 ──


async def upsert_energy_data(
    db: AsyncSession,
    device_config_id: UUID,
    timestamp: datetime,
    value: float,
    unit: str,
    platform_raw_data: dict[str, Any] | None = None,
) -> EnergyData:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(EnergyData).values(
        device_config_id=device_config_id,
        timestamp=timestamp,
        value=value,
        unit=unit,
        platform_raw_data=platform_raw_data,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_energy_data_device_timestamp",
        set_={"value": value, "platform_raw_data": platform_raw_data},
    )
    returning_stmt = stmt.returning(EnergyData)
    result = await db.execute(returning_stmt)
    return result.scalar_one()


async def list_energy_data(
    db: AsyncSession,
    *,
    device_config_id: UUID | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyData], int]:
    query = select(EnergyData).where(
        EnergyData.is_deleted == False  # noqa: E712
    )
    if device_config_id:
        query = query.where(EnergyData.device_config_id == device_config_id)
    if start_time:
        query = query.where(EnergyData.timestamp >= start_time)
    if end_time:
        query = query.where(EnergyData.timestamp <= end_time)
    if energy_type or workshop:
        query = query.join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        if energy_type:
            query = query.where(EnergyDeviceConfig.energy_type == energy_type)
        if workshop:
            query = query.where(EnergyDeviceConfig.workshop == workshop)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyData.timestamp.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_energy_statistics(
    db: AsyncSession,
    *,
    group_by: str,
    energy_type: str | None = None,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    if group_by == "workshop":
        group_col = EnergyDeviceConfig.workshop
    elif group_by == "production_line":
        group_col = EnergyDeviceConfig.production_line
    else:
        group_col = EnergyDeviceConfig.device_name

    query = (
        select(
            group_col.label("group_key"),
            func.sum(EnergyData.value).label("total_value"),
            EnergyData.unit,
            func.count(EnergyData.id).label("data_count"),
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
        )
        .group_by(group_col, EnergyData.unit)
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)

    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "group_key": row.group_key,
            "total_value": float(row.total_value or 0),
            "unit": row.unit,
            "data_count": row.data_count,
        }
        for row in rows
    ]


# ── 采集日志 ──


# ── 总览统计 ──


async def get_overview_summary(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """按能源类型汇总能耗"""
    query = (
        select(
            EnergyDeviceConfig.energy_type,
            func.sum(EnergyData.value).label("total_value"),
            EnergyData.unit,
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
        )
        .group_by(EnergyDeviceConfig.energy_type, EnergyData.unit)
    )
    result = await db.execute(query)
    return [
        {
            "energy_type": row.energy_type,
            "total_value": float(row.total_value or 0),
            "unit": row.unit,
        }
        for row in result.all()
    ]


async def get_overview_trend(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    energy_type: str | None = None,
) -> list[dict[str, Any]]:
    """按小时获取能耗趋势数据"""
    query = (
        select(
            EnergyData.timestamp,
            EnergyDeviceConfig.energy_type,
            func.sum(EnergyData.value).label("total_value"),
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
        )
        .group_by(EnergyData.timestamp, EnergyDeviceConfig.energy_type)
        .order_by(EnergyData.timestamp.asc())
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)

    result = await db.execute(query)
    return [
        {
            "time": row.timestamp.isoformat(),
            "value": float(row.total_value or 0),
            "type": row.energy_type,
        }
        for row in result.all()
    ]


async def create_collect_log(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyCollectLog:
    obj = EnergyCollectLog(**data)
    db.add(obj)
    await db.flush()
    return obj


async def list_collect_logs(
    db: AsyncSession,
    *,
    platform_code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyCollectLog], int]:
    query = select(EnergyCollectLog).where(
        EnergyCollectLog.is_deleted == False  # noqa: E712
    )
    if platform_code:
        query = query.where(EnergyCollectLog.platform_code == platform_code)
    if status:
        query = query.where(EnergyCollectLog.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyCollectLog.collect_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_collect_log_detail(
    db: AsyncSession,
    log_id: UUID,
    time_window_seconds: int = 30,
) -> tuple[EnergyCollectLog | None, list[tuple[EnergyData, EnergyDeviceConfig]]]:
    """获取采集日志详情及关联的能耗数据。

    通过 platform_code + 时间窗口匹配 EnergyData 和 EnergyCollectLog。
    """
    log = await db.scalar(
        select(EnergyCollectLog).where(
            EnergyCollectLog.id == log_id,
            EnergyCollectLog.is_deleted == False,  # noqa: E712
        )
    )
    if log is None:
        return None, []

    from datetime import timedelta

    window_start = log.collect_time - timedelta(seconds=time_window_seconds)
    window_end = log.collect_time + timedelta(seconds=time_window_seconds)

    query = (
        select(EnergyData, EnergyDeviceConfig)
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyDeviceConfig.platform_code == log.platform_code,
            EnergyData.collected_at >= window_start,
            EnergyData.collected_at <= window_end,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .order_by(EnergyData.timestamp.desc())
    )
    result = await db.execute(query)
    rows = list(result.all())

    return log, rows


# ── 预警规则 ──


async def create_alert_rule(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyAlertRule:
    obj = EnergyAlertRule(**data)
    db.add(obj)
    await db.flush()
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.id == obj.id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one()


async def get_alert_rule_by_id(
    db: AsyncSession, rule_id: UUID
) -> EnergyAlertRule | None:
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.id == rule_id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_alert_rules(
    db: AsyncSession,
    *,
    energy_type: str | None = None,
    alert_level: str | None = None,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyAlertRule], int]:
    query = select(EnergyAlertRule).where(
        EnergyAlertRule.is_deleted == False  # noqa: E712
    )
    if energy_type:
        query = query.where(EnergyAlertRule.energy_type == energy_type)
    if alert_level:
        query = query.where(EnergyAlertRule.alert_level == alert_level)
    if is_enabled is not None:
        query = query.where(EnergyAlertRule.is_enabled == is_enabled)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyAlertRule.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_alert_rule(
    db: AsyncSession, rule_id: UUID, data: dict[str, Any]
) -> EnergyAlertRule | None:
    obj = await get_alert_rule_by_id(db, rule_id)
    if obj is None:
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.id == rule_id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def delete_alert_rule(db: AsyncSession, rule_id: UUID) -> bool:
    obj = await get_alert_rule_by_id(db, rule_id)
    if obj is None:
        return False
    obj.is_deleted = True
    await db.flush()
    return True


# ── 预警记录 ──


async def create_alert_record(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyAlertRecord:
    obj = EnergyAlertRecord(**data)
    db.add(obj)
    await db.flush()
    result = await db.execute(
        select(EnergyAlertRecord).where(
            EnergyAlertRecord.id == obj.id,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one()


async def get_alert_record_by_id(
    db: AsyncSession, record_id: UUID
) -> EnergyAlertRecord | None:
    result = await db.execute(
        select(EnergyAlertRecord).where(
            EnergyAlertRecord.id == record_id,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_alert_records(
    db: AsyncSession,
    *,
    energy_type: str | None = None,
    alert_level: str | None = None,
    status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyAlertRecord], int]:
    query = select(EnergyAlertRecord).where(
        EnergyAlertRecord.is_deleted == False  # noqa: E712
    )
    if energy_type:
        query = query.where(EnergyAlertRecord.energy_type == energy_type)
    if alert_level:
        query = query.where(EnergyAlertRecord.alert_level == alert_level)
    if status:
        query = query.where(EnergyAlertRecord.status == status)
    if start_time:
        query = query.where(EnergyAlertRecord.alert_time >= start_time)
    if end_time:
        query = query.where(EnergyAlertRecord.alert_time <= end_time)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyAlertRecord.alert_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_alert_record(
    db: AsyncSession, record_id: UUID, data: dict[str, Any]
) -> EnergyAlertRecord | None:
    obj = await get_alert_record_by_id(db, record_id)
    if obj is None:
        return None
    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()
    result = await db.execute(
        select(EnergyAlertRecord).where(
            EnergyAlertRecord.id == record_id,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()
