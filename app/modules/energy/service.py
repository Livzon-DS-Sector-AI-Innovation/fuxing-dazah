"""Energy business workflows live here."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.models import (
    EnergyCollectLog,
    EnergyData,
    EnergyDeviceConfig,
)
from app.modules.energy.schemas import (
    CollectTriggerRequest,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
)

logger = logging.getLogger(__name__)


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
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyDeviceConfig], int]:
    return await repo.list_device_configs(
        db,
        platform_code=platform_code,
        energy_type=energy_type,
        workshop=workshop,
        is_enabled=is_enabled,
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


async def _get_target_hour() -> datetime:
    """获取目标采集小时：上一个整点"""
    now = datetime.now()
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


async def trigger_collection(
    db: AsyncSession, request: CollectTriggerRequest
) -> dict[str, Any]:
    """触发采集任务"""
    target_hour = await _get_target_hour()

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
