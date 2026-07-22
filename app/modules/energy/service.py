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
from app.modules.energy.collect_settings import CST
from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyData,
    EnergyDeviceConfig,
    EnergyTypeConfig,
    EnergyWorkshopConfig,
)
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    CollectTriggerRequest,
    EnergyAlertRuleCreate,
    EnergyAlertRuleUpdate,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
    EnergyTypeConfigCreate,
    EnergyTypeConfigUpdate,
    EnergyWorkshopConfigCreate,
    EnergyWorkshopConfigUpdate,
)

logger = logging.getLogger(__name__)


async def _get_unit_by_energy_type(db: AsyncSession, energy_type: str) -> str:
    """从 EnergyTypeConfig 获取能源类型的计量单位。未配置时抛出 NotFoundException。"""
    config = await repo.get_type_config_by_code(db, energy_type)
    if config is None:
        raise NotFoundException("能源类型配置", f"{energy_type}（请先在能源类型可视化配置中添加该类型）")
    return config.unit


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
    create_data = data.model_dump()
    create_data["unit"] = await _get_unit_by_energy_type(db, data.energy_type)
    return await repo.create_device_config(db, create_data)


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

    # energy_type 变更时，同步 unit 为 EnergyTypeConfig 中的单位
    if "energy_type" in update_data:
        update_data["unit"] = await _get_unit_by_energy_type(db, update_data["energy_type"])

    result = await repo.update_device_config(db, config_id, update_data)
    assert result is not None  # already verified existence above
    return result


async def delete_device_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_device_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("设备配置", str(config_id))
    await repo.delete_device_config(db, config_id)


async def _collect_daily_summary(
    db: AsyncSession,
    device: EnergyDeviceConfig,
    target_day: datetime,
) -> float | None:
    """采集日汇总数据。

    优先使用适配器的 is_daily=True 模式（一次 API 调用拿全天总值）；
    若适配器不支持则回退到逐小时采集（24 次调用累加）。
    返回总和值；全部失败则返回 None。
    """
    adapter = ADAPTERS.get(device.platform_code)
    if adapter is None:
        logger.warning("未找到平台适配器: %s，跳过日汇总采集", device.platform_code)
        return None

    unit = await _get_unit_by_energy_type(db, device.energy_type)

    # ── 优先：单次全天 API 调用 ──
    try:
        results = await adapter.fetch_energy_data(
            [device.platform_device_code], target_day, device.api_endpoint, is_daily=True
        )
        for cr in results:
            if cr.device_code == device.platform_device_code:
                value = float(cr.value)
                await repo.upsert_energy_data(
                    db,
                    device_config_id=device.id,
                    timestamp=target_day,
                    value=value,
                    unit=unit,
                    platform_raw_data={"daily_sum": True, "source": "single_api"},
                )
                logger.info(
                    "日汇总采集完成(单次API): device=%s, day=%s, value=%.4f",
                    device.device_name,
                    target_day.strftime("%Y-%m-%d"),
                    value,
                )
                return value
        logger.warning(
            "日汇总采集: 未找到匹配设备数据, device=%s, day=%s",
            device.device_name, target_day.strftime("%Y-%m-%d"),
        )
        return None
    except NotImplementedError:
        logger.debug(
            "平台 %s 不支持 is_daily=True，回退逐小时采集", device.platform_code
        )

    # ── 回退：逐小时采集并累加 ──
    total = 0.0
    hours_collected = 0

    for hour in range(24):
        target_hour = target_day.replace(hour=hour)
        try:
            results = await adapter.fetch_energy_data(
                [device.platform_device_code], target_hour, device.api_endpoint
            )
        except NotImplementedError:
            logger.debug(
                "平台 %s 适配器尚未实现，跳过日汇总采集", device.platform_code
            )
            return None
        except Exception:
            logger.exception(
                "日汇总逐小时采集异常: device=%s, hour=%s",
                device.device_name,
                target_hour.strftime("%Y-%m-%d %H:00"),
            )
            continue

        for cr in results:
            if cr.device_code == device.platform_device_code:
                total += float(cr.value)
                hours_collected += 1
                break

    if hours_collected == 0:
        logger.warning(
            "日汇总采集全部失败: device=%s, day=%s",
            device.device_name,
            target_day.strftime("%Y-%m-%d"),
        )
        return None

    await repo.upsert_energy_data(
        db,
        device_config_id=device.id,
        timestamp=target_day,
        value=total,
        unit=unit,
        platform_raw_data={
            "daily_sum": True,
            "hours_collected": hours_collected,
        },
    )
    logger.info(
        "日汇总采集完成(逐小时): device=%s, day=%s, value=%.4f, hours=%d/24",
        device.device_name,
        target_day.strftime("%Y-%m-%d"),
        total,
        hours_collected,
    )
    return total


async def trigger_collection(
    db: AsyncSession, request: CollectTriggerRequest
) -> dict[str, Any]:
    """手动触发采集 — 采集昨天全天汇总数据。

    无论今天几点触发，始终采集昨天 00:00 ~ 23:59 的总数据，
    每个设备写入一条日汇总记录。
    """
    now = datetime.now(CST)
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    if request.platform_code:
        platform_codes = [request.platform_code]
    else:
        platform_codes = await repo.get_distinct_enabled_platforms(db)

    results: dict[str, Any] = {}
    for platform_code in platform_codes:
        adapter = ADAPTERS.get(platform_code)
        if adapter is None:
            results[platform_code] = {
                "status": "failed",
                "error": f"未找到平台适配器: {platform_code}",
            }
            continue

        devices = await repo.get_enabled_devices_by_platform(db, platform_code)
        if not devices:
            results[platform_code] = {
                "status": "success",
                "device_count": 0,
                "success_count": 0,
            }
            continue

        success_count = 0
        for device in devices:
            try:
                value = await _collect_daily_summary(db, device, yesterday)
                if value is not None:
                    success_count += 1
            except Exception:
                logger.exception(
                    "手动采集异常: device=%s, day=%s",
                    device.device_name,
                    yesterday.strftime("%Y-%m-%d"),
                )

        status = (
            "success" if success_count == len(devices)
            else "partial" if success_count > 0
            else "failed"
        )

        try:
            await repo.create_collect_log(
                db,
                {
                    "platform_code": platform_code,
                    "collect_time": now,
                    "status": status,
                    "device_count": len(devices),
                    "success_count": success_count,
                    "error_message": f"手动触发: {yesterday.strftime('%Y-%m-%d')} 日汇总" if status != "success" else None,
                },
            )
        except Exception:
            logger.exception(
                "采集日志写入失败（不影响能耗数据）: %s", platform_code
            )

        results[platform_code] = {
            "status": status,
            "device_count": len(devices),
            "success_count": success_count,
            "target_day": yesterday.strftime("%Y-%m-%d"),
        }

    return results


async def list_departments(db: AsyncSession) -> list[dict[str, Any]]:
    return await repo.list_departments(db)


async def list_equipments_for_select(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """查询设备台账中在用的设备列表（供数据源配置关联设备下拉使用）。"""
    return await repo.list_equipments_for_select(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )


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


async def list_energy_data_history(
    db: AsyncSession,
    *,
    device_config_id: UUID | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    keyword: str | None = None,
    granularity: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询能耗数据历史明细（含设备信息）。"""
    return await repo.list_energy_data_history(
        db,
        device_config_id=device_config_id,
        energy_type=energy_type,
        workshop=workshop,
        start_time=start_time,
        end_time=end_time,
        keyword=keyword,
        granularity=granularity,
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


async def delete_energy_data(db: AsyncSession, data_id: UUID) -> bool:
    """软删除单条能耗数据。"""
    if not await repo.delete_energy_data(db, data_id):
        raise NotFoundException("能耗数据", str(data_id))
    return True


async def batch_delete_energy_data(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除能耗数据，返回删除数量。"""
    return await repo.batch_delete_energy_data(db, ids)


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


async def clear_collect_logs(db: AsyncSession) -> int:
    """清空所有采集日志（软删除）。"""
    return await repo.clear_collect_logs(db)


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

    # 预加载能源类型单位映射
    type_configs = await repo.list_enabled_type_configs(db)
    unit_map: dict[str, str] = {c.type_code: c.unit for c in type_configs}

    for energy_data, device_config in rows:
        # 日汇总记录的数据覆盖范围为全天，小时记录为 1 小时
        is_daily = (
            energy_data.platform_raw_data
            and energy_data.platform_raw_data.get("daily_sum") is True
        )
        data_start = energy_data.timestamp
        data_end = energy_data.timestamp + (timedelta(days=1) if is_daily else timedelta(hours=1))
        devices.append({
            "device_name": device_config.device_name,
            "platform_device_code": device_config.platform_device_code,
            "energy_type": device_config.energy_type,
            "value": float(energy_data.value),
            "unit": unit_map.get(device_config.energy_type, energy_data.unit),
            "data_timestamp": energy_data.timestamp,
            "data_time_range_end": data_end,
        })
        if time_range_start is None or data_start < time_range_start:
            time_range_start = data_start
        if time_range_end is None or data_end > time_range_end:
            time_range_end = data_end

    # 确保 time_range_end 至少比 time_range_start 合理（避免起止一致）
    if time_range_start is not None and time_range_end is not None:
        if time_range_end <= time_range_start:
            time_range_end = time_range_start + timedelta(days=1)

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
    granularity: str = "hourly",
) -> dict[str, Any]:
    summary_rows = await repo.get_overview_summary(db, start_time, end_time)
    # 从 DB 读取启用的能源类型配置，动态初始化 summary
    type_configs = await repo.list_enabled_type_configs(db)
    summary: dict[str, float] = {c.type_code: 0.0 for c in type_configs}
    seen_units: dict[str, set[str]] = {c.type_code: set() for c in type_configs}
    for row in summary_rows:
        et = row["energy_type"]
        summary[et] = summary.get(et, 0) + row["total_value"]
        seen_units.setdefault(et, set()).add(row["unit"])
    # 同能源类型存在多种计量单位时告警
    for et, units in seen_units.items():
        if len(units) > 1:
            logger.warning(
                "能源类型 %s 在查询范围内存在多种计量单位: %s，合计值可能不准确",
                et,
                units,
            )

    trend_rows = await repo.get_overview_trend(
        db, start_time, end_time, energy_type=energy_type, granularity=granularity
    )

    distribution_rows = await repo.get_energy_statistics(
        db,
        group_by="workshop",
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
    )

    production_line_rows = await repo.get_energy_statistics(
        db,
        group_by="production_line",
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
    )

    # 向后兼容：total_<code> 格式 + total_gas
    result_summary: dict[str, float] = {
        f"total_{et}": val for et, val in summary.items()
    }
    result_summary.setdefault("total_gas", 0.0)
    # 新增：type_code 直接映射 + 类型元数据
    result_summary.update(summary)

    # 能源类型元数据（供前端动态渲染）
    type_metadata = [
        {
            "type_code": c.type_code,
            "display_name": c.display_name,
            "unit": c.unit,
            "color": c.color,
            "icon": c.icon,
        }
        for c in type_configs
    ]

    return {
        "summary": result_summary,
        "trend": trend_rows,
        "distribution": distribution_rows,
        "workshop_distribution": distribution_rows,
        "production_line_distribution": production_line_rows,
        "type_metadata": type_metadata,
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


# ── 能源类型可视化配置 ──


async def create_type_config(
    db: AsyncSession, data: EnergyTypeConfigCreate
) -> EnergyTypeConfig:
    existing = await repo.get_type_config_by_code(db, data.type_code)
    if existing is not None:
        raise DuplicateException("能源类型编码", data.type_code)
    return await repo.create_type_config(db, data.model_dump())


async def get_type_config(db: AsyncSession, config_id: UUID) -> EnergyTypeConfig:
    obj = await repo.get_type_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("能源类型配置", str(config_id))
    return obj


async def list_type_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[EnergyTypeConfig], int]:
    return await repo.list_type_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )


async def list_enabled_type_configs(
    db: AsyncSession,
) -> list[EnergyTypeConfig]:
    return await repo.list_enabled_type_configs(db)


async def update_type_config(
    db: AsyncSession, config_id: UUID, data: EnergyTypeConfigUpdate
) -> EnergyTypeConfig:
    existing = await repo.get_type_config_by_id(db, config_id)
    if existing is None:
        raise NotFoundException("能源类型配置", str(config_id))
    result = await repo.update_type_config(
        db, config_id, data.model_dump(exclude_unset=True)
    )
    assert result is not None
    return result


async def delete_type_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_type_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("能源类型配置", str(config_id))
    await repo.delete_type_config(db, config_id)


# ── 车间预警配置 ──


async def create_workshop_config(
    db: AsyncSession, data: EnergyWorkshopConfigCreate
) -> EnergyWorkshopConfig:
    existing = await repo.get_workshop_config_by_workshop(db, data.workshop)
    if existing is not None:
        raise DuplicateException("车间预警配置", data.workshop)
    create_data = data.model_dump()
    return await repo.create_workshop_config(db, create_data)


async def get_workshop_config(db: AsyncSession, config_id: UUID) -> EnergyWorkshopConfig:
    obj = await repo.get_workshop_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("车间预警配置", str(config_id))
    return obj


async def list_workshop_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyWorkshopConfig], int]:
    return await repo.list_workshop_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )


async def update_workshop_config(
    db: AsyncSession, config_id: UUID, data: EnergyWorkshopConfigUpdate
) -> EnergyWorkshopConfig:
    existing = await repo.get_workshop_config_by_id(db, config_id)
    if existing is None:
        raise NotFoundException("车间预警配置", str(config_id))
    update_data = data.model_dump(exclude_unset=True)
    if "workshop" in update_data:
        dup = await repo.get_workshop_config_by_workshop(db, update_data["workshop"])
        if dup is not None and dup.id != config_id:
            raise DuplicateException("车间预警配置", update_data["workshop"])
    result = await repo.update_workshop_config(db, config_id, update_data)
    assert result is not None
    return result


async def delete_workshop_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_workshop_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("车间预警配置", str(config_id))
    await repo.soft_delete_workshop_config(db, config_id)


async def get_personnel_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    """获取负责人候选人列表（从平台 identity.users 查询）。"""
    return await repo.get_personnel_candidates(db)


# ── 车间预警评估 ──


async def evaluate_workshop_alerts(db: AsyncSession) -> dict[str, Any]:
    """评估所有启用车间的能耗预警。

    对每个 (workshop, energy_type) 组合：
    1. 查询昨天总能耗
    2. 计算近 30 天日均（不足 30 天取实际天数）
    3. 若 昨天 > 平均 * 1.15，创建预警记录 + 发送飞书通知

    Returns:
        {"checked": int, "triggered": int, "errors": int}
    """
    from datetime import datetime, timedelta

    from app.platform.integrations.feishu.notification import send_user_card

    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    configs = await repo.get_enabled_workshop_configs(db)
    if not configs:
        return {"checked": 0, "triggered": 0, "errors": 0}

    # 获取所有能源类型单位映射
    type_configs = await repo.list_enabled_type_configs(db)
    unit_map = {c.type_code: c.unit for c in type_configs}

    # 获取所有车间-能源类型组合
    all_combos = await repo.get_distinct_workshop_energy_types(db)

    checked = 0
    triggered = 0
    errors = 0

    for config in configs:
        # 防重复：今天已检查过则跳过
        if config.last_checked_at is not None:
            if config.last_checked_at.date() == now.date():
                continue

        # 该车间下的能源类型
        workshop_combos = [
            c for c in all_combos if c["workshop"] == config.workshop
        ]
        if not workshop_combos:
            continue

        # 确保系统规则存在
        energy_types = [c["energy_type"] for c in workshop_combos]
        await repo.ensure_system_rules(db, config.workshop, energy_types, unit_map)

        # 获取 heads 中的 feishu_open_id
        heads = config.heads or []
        open_ids = [h.get("feishu_open_id", "") for h in heads if h.get("feishu_open_id")]

        for combo in workshop_combos:
            energy_type = combo["energy_type"]
            unit = unit_map.get(energy_type, "")

            try:
                # 查重：当天已有预警则跳过
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                existing_record = await repo.find_today_alert_record(
                    db, config.workshop, energy_type, today_start
                )
                if existing_record is not None:
                    checked += 1
                    continue

                # 查询昨日能耗
                yesterday_consumption = await repo.get_workshop_daily_consumption(
                    db, config.workshop, energy_type, yesterday
                )
                if yesterday_consumption is None or yesterday_consumption == 0:
                    checked += 1
                    continue

                # 计算近 30 天平均值
                avg_consumption = await repo.get_workshop_avg_consumption(
                    db, config.workshop, energy_type, yesterday, max_days=30
                )
                if avg_consumption is None or avg_consumption == 0:
                    checked += 1
                    continue

                # 判断是否超过 115%
                threshold = avg_consumption * 1.15
                if yesterday_consumption <= threshold:
                    checked += 1
                    continue

                # 获取系统规则
                sys_rule = await repo.get_system_alert_rule(db, config.workshop, energy_type)
                rule_id = sys_rule.id if sys_rule else None

                # 创建预警记录
                from decimal import Decimal
                _ = await repo.create_alert_record(db, {
                    "rule_id": rule_id,
                    "workshop": config.workshop,
                    "energy_type": energy_type,
                    "alert_level": "warning",
                    "trigger_value": Decimal(str(yesterday_consumption)),
                    "threshold_value": Decimal(str(threshold)),
                    "unit": unit,
                    "alert_time": now,
                    "status": "pending",
                })

                # 发送飞书通知
                notify_title = f"⚠️ 能耗预警 - {config.workshop}"
                notify_content = (
                    f"**{config.workshop}** 车间昨日 **{energy_type}** 能耗异常：\n\n"
                    f"- 昨日用量：**{yesterday_consumption:,.2f} {unit}**\n"
                    f"- 近30日均值：{avg_consumption:,.2f} {unit}\n"
                    f"- 预警阈值（均值×115%）：{threshold:,.2f} {unit}\n"
                    f"- 超出比例：**{((yesterday_consumption / avg_consumption - 1) * 100):.1f}%**\n\n"
                    f"检测时间：{now.strftime('%Y-%m-%d %H:%M')}"
                )

                for open_id in open_ids:
                    success = await send_user_card(open_id, notify_title, notify_content)
                    if not success:
                        logger.warning(
                            "车间预警飞书通知失败: workshop=%s, energy_type=%s, open_id=%s",
                            config.workshop, energy_type, open_id,
                        )

                triggered += 1
                logger.info(
                    "车间能耗预警触发: workshop=%s, energy_type=%s, "
                    "yesterday=%.2f, avg=%.2f, threshold=%.2f",
                    config.workshop, energy_type,
                    yesterday_consumption, avg_consumption, threshold,
                )

            except Exception:
                logger.exception(
                    "车间能耗预警评估异常: workshop=%s, energy_type=%s",
                    config.workshop, energy_type,
                )
                errors += 1

            checked += 1

        # 更新 last_checked_at
        await repo.update_workshop_config(db, config.id, {"last_checked_at": now})

    return {"checked": checked, "triggered": triggered, "errors": errors}


