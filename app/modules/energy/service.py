"""Energy business workflows live here."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyData,
    EnergyDeviceConfig,
)
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    CollectTriggerRequest,
    EnergyAlertRuleCreate,
    EnergyAlertRuleUpdate,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
)

logger = logging.getLogger(__name__)

# 中国标准时间 UTC+8
CST = timezone(timedelta(hours=8))


async def create_device_config(
    db: AsyncSession, data: EnergyDeviceConfigCreate
) -> EnergyDeviceConfig:
    if await repo.exists_device_config(
        db, data.platform_code, data.platform_device_code
    ):
        raise DuplicateException(
            "设备配置",
            f"{data.platform_code}:{data.platform_device_code}",
        )
    return await repo.create_device_config(db, data.model_dump())


async def get_device_config(db: AsyncSession, config_id: UUID) -> EnergyDeviceConfig:
    obj = await repo.get_device_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("设备配置", str(config_id))
    return obj


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
    return await repo.list_device_configs(
        db,
        platform_code=platform_code,
        energy_type=energy_type,
        workshop=workshop,
        is_enabled=is_enabled,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


async def update_device_config(
    db: AsyncSession, config_id: UUID, data: EnergyDeviceConfigUpdate
) -> EnergyDeviceConfig:
    existing = await repo.get_device_config_by_id(db, config_id)
    if existing is None:
        raise NotFoundException("设备配置", str(config_id))

    update_data = data.model_dump(exclude_unset=True)
    if "platform_code" in update_data or "platform_device_code" in update_data:
        pc = update_data.get("platform_code", existing.platform_code)
        pdc = update_data.get(
            "platform_device_code", existing.platform_device_code
        )
        if await repo.exists_device_config(db, pc, pdc, exclude_id=config_id):
            raise DuplicateException("设备配置", f"{pc}:{pdc}")

    result = await repo.update_device_config(db, config_id, update_data)
    assert result is not None  # already verified existence above
    return result


async def delete_device_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_device_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("设备配置", str(config_id))
    await repo.delete_device_config(db, config_id)


def get_target_hour() -> datetime:
    """获取目标采集小时：上一个整点（时区感知）。"""
    now = datetime.now(CST)
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


async def trigger_collection(
    db: AsyncSession, request: CollectTriggerRequest
) -> dict[str, Any]:
    """触发采集任务"""
    target_hour = get_target_hour()

    if request.platform_code:
        platform_codes = [request.platform_code]
    else:
        platform_codes = list(ADAPTERS.keys())

    results: dict[str, Any] = {}
    for platform_code in platform_codes:
        adapter = ADAPTERS.get(platform_code)
        if adapter is None:
            results[platform_code] = {
                "status": "failed",
                "error": f"未找到平台适配器: {platform_code}",
            }
            continue

        devices = await repo.get_enabled_devices_by_platform(
            db, platform_code
        )
        if not devices:
            results[platform_code] = {
                "status": "success",
                "device_count": 0,
                "success_count": 0,
            }
            continue

        device_codes = [d.platform_device_code for d in devices]
        device_map = {d.platform_device_code: d for d in devices}
        api_endpoint = devices[0].api_endpoint

        try:
            collect_results = await adapter.fetch_energy_data(
                device_codes, target_hour, api_endpoint
            )

            success_count = 0
            for cr in collect_results:
                device = device_map.get(cr.device_code)
                if device is None:
                    continue
                await repo.upsert_energy_data(
                    db,
                    device_config_id=device.id,
                    timestamp=cr.timestamp,
                    value=cr.value,
                    unit=cr.unit,
                    platform_raw_data=cr.raw_data,
                )
                success_count += 1

            status = (
                "success"
                if success_count == len(device_codes)
                else "partial"
            )
            await repo.create_collect_log(
                db,
                {
                    "platform_code": platform_code,
                    "collect_time": datetime.now(),
                    "status": status,
                    "device_count": len(device_codes),
                    "success_count": success_count,
                },
            )
            results[platform_code] = {
                "status": status,
                "device_count": len(device_codes),
                "success_count": success_count,
            }

        except Exception as e:
            logger.exception("采集失败: platform=%s", platform_code)
            await repo.create_collect_log(
                db,
                {
                    "platform_code": platform_code,
                    "collect_time": datetime.now(),
                    "status": "failed",
                    "device_count": len(device_codes),
                    "success_count": 0,
                    "error_message": str(e),
                },
            )
            results[platform_code] = {
                "status": "failed",
                "device_count": len(device_codes),
                "success_count": 0,
                "error": str(e),
            }

    return results


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
    return await repo.list_energy_data(
        db,
        device_config_id=device_config_id,
        energy_type=energy_type,
        workshop=workshop,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


async def get_energy_statistics(
    db: AsyncSession,
    *,
    group_by: str = "workshop",
    energy_type: str | None = None,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    return await repo.get_energy_statistics(
        db,
        group_by=group_by,
        energy_type=energy_type,
        start_time=start_time,
        end_time=end_time,
    )


async def list_collect_logs(
    db: AsyncSession,
    *,
    platform_code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyCollectLog], int]:
    return await repo.list_collect_logs(
        db,
        platform_code=platform_code,
        status=status,
        page=page,
        page_size=page_size,
    )


async def get_collect_log_detail(
    db: AsyncSession, log_id: UUID
) -> dict[str, Any]:
    """获取采集日志详情，包含设备数据和时间范围。"""
    log, rows = await repo.get_collect_log_detail(db, log_id)
    if log is None:
        raise NotFoundException("采集日志", str(log_id))

    devices: list[dict[str, Any]] = []
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None

    for energy_data, device_config in rows:
        devices.append({
            "device_name": device_config.device_name,
            "platform_device_code": device_config.platform_device_code,
            "energy_type": device_config.energy_type,
            "value": float(energy_data.value),
            "unit": energy_data.unit,
            "data_timestamp": energy_data.timestamp,
        })
        if time_range_start is None or energy_data.timestamp < time_range_start:
            time_range_start = energy_data.timestamp
        if time_range_end is None or energy_data.timestamp > time_range_end:
            time_range_end = energy_data.timestamp

    return {
        "id": str(log.id),
        "platform_code": log.platform_code,
        "collect_time": log.collect_time,
        "status": log.status,
        "device_count": log.device_count,
        "success_count": log.success_count,
        "error_message": log.error_message,
        "created_at": log.created_at,
        "devices": devices,
        "time_range_start": time_range_start,
        "time_range_end": time_range_end,
    }


# ── 总览 ──


async def get_overview(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    energy_type: str | None = None,
) -> dict[str, Any]:
    summary_rows = await repo.get_overview_summary(db, start_time, end_time)
    summary: dict[str, float] = {"electricity": 0, "water": 0, "gas": 0}
    for row in summary_rows:
        et = row["energy_type"]
        if et in summary:
            summary[et] = row["total_value"]

    trend_rows = await repo.get_overview_trend(
        db, start_time, end_time, energy_type=energy_type
    )

    distribution_rows = await repo.get_energy_statistics(
        db,
        group_by="workshop",
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
    )

    return {
        "summary": {
            "total_electricity": summary["electricity"],
            "total_water": summary["water"],
            "total_gas": summary["gas"],
        },
        "trend": trend_rows,
        "distribution": distribution_rows,
    }


# ── 预警规则 ──


async def create_alert_rule(
    db: AsyncSession, data: EnergyAlertRuleCreate
) -> EnergyAlertRule:
    return await repo.create_alert_rule(db, data.model_dump())


async def get_alert_rule(db: AsyncSession, rule_id: UUID) -> EnergyAlertRule:
    obj = await repo.get_alert_rule_by_id(db, rule_id)
    if obj is None:
        raise NotFoundException("预警规则", str(rule_id))
    return obj


async def list_alert_rules(
    db: AsyncSession,
    *,
    energy_type: str | None = None,
    alert_level: str | None = None,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyAlertRule], int]:
    return await repo.list_alert_rules(
        db,
        energy_type=energy_type,
        alert_level=alert_level,
        is_enabled=is_enabled,
        page=page,
        page_size=page_size,
    )


async def update_alert_rule(
    db: AsyncSession, rule_id: UUID, data: EnergyAlertRuleUpdate
) -> EnergyAlertRule:
    existing = await repo.get_alert_rule_by_id(db, rule_id)
    if existing is None:
        raise NotFoundException("预警规则", str(rule_id))
    result = await repo.update_alert_rule(
        db, rule_id, data.model_dump(exclude_unset=True)
    )
    assert result is not None
    return result


async def delete_alert_rule(db: AsyncSession, rule_id: UUID) -> None:
    obj = await repo.get_alert_rule_by_id(db, rule_id)
    if obj is None:
        raise NotFoundException("预警规则", str(rule_id))
    await repo.delete_alert_rule(db, rule_id)


# ── 预警记录 ──


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
    return await repo.list_alert_records(
        db,
        energy_type=energy_type,
        alert_level=alert_level,
        status=status,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )


async def process_alert_record(
    db: AsyncSession, record_id: UUID, request: AlertRecordProcessRequest
) -> EnergyAlertRecord:
    existing = await repo.get_alert_record_by_id(db, record_id)
    if existing is None:
        raise NotFoundException("预警记录", str(record_id))
    result = await repo.update_alert_record(
        db,
        record_id,
        {
            "status": request.status,
            "process_note": request.process_note,
            "processed_at": datetime.now(),
        },
    )
    assert result is not None
    return result
