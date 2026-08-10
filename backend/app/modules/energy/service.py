"""Energy business workflows live here."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.collect_settings import CST
from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyDailyPushConfig,
    EnergyData,
    EnergyDeviceConfig,
    EnergyNitrogenPushConfig,
    EnergyTypeConfig,
    EnergyWorkshopConfig,
)
from app.modules.energy.schemas import (
    AlertRecordProcessRequest,
    CollectTriggerRequest,
    EnergyAlertRuleCreate,
    EnergyAlertRuleUpdate,
    EnergyDailyPushConfigCreate,
    EnergyDailyPushConfigUpdate,
    EnergyDeviceConfigCreate,
    EnergyDeviceConfigUpdate,
    EnergyNitrogenPushConfigCreate,
    EnergyNitrogenPushConfigUpdate,
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
    # 部门级别时，区域字段置空
    if not create_data.get("is_region_level", False):
        create_data["production_line"] = None
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

    # 部门级别时，区域字段置空
    if update_data.get("is_region_level") is False:
        update_data["production_line"] = None

    result = await repo.update_device_config(db, config_id, update_data)
    assert result is not None  # already verified existence above
    return result


async def delete_device_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_device_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("设备配置", str(config_id))
    await repo.delete_device_config(db, config_id)


async def trigger_collection(
    db: AsyncSession, request: CollectTriggerRequest
) -> dict[str, Any]:
    """手动触发采集 — 复用并发采集逻辑，所有平台+设备并发执行。"""
    import asyncio

    from app.modules.energy.scheduler import _collect_platform_devices

    now = datetime.now(CST)
    yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    if request.platform_code:
        platform_codes = [request.platform_code]
    else:
        platform_codes = await repo.get_distinct_enabled_platforms(db)

    # 平台并发执行
    tasks = [
        _collect_platform_devices(pc, yesterday, now) for pc in platform_codes
    ]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, Any] = {}
    for i, r in enumerate(gathered):
        pc = platform_codes[i]
        if isinstance(r, Exception):
            logger.exception("手动采集异常: platform=%s", pc)
            results[pc] = {"status": "failed", "error": str(r)}
            continue
        if r is None:
            results[pc] = {
                "status": "failed",
                "error": f"未找到平台适配器: {pc}",
            }
            continue
        # _collect_platform_devices 已在内部写入采集日志，此处仅汇总结果
        results[pc] = {
            "status": r["status"],
            "device_count": r["device_count"],
            "success_count": r["success_count"],

            "target_day": yesterday.strftime("%Y-%m-%d"),
        }

    return results


async def list_departments(db: AsyncSession) -> list[dict[str, Any]]:
    return await repo.list_departments(db)


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


async def update_energy_data(
    db: AsyncSession, data_id: UUID, value: float,
) -> EnergyData:
    """修改单条能耗数据的值。"""
    result = await repo.update_energy_data_value(db, data_id, value)
    if result is None:
        raise NotFoundException("能耗数据", str(data_id))
    # UPDATE 后 re-fetch 避免 MissingGreenlet
    updated = await repo.get_energy_data_by_id(db, data_id)
    assert updated is not None
    return updated


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
        # 判断是否为日汇总数据（daily_aggregated 标记）
        is_daily = isinstance(energy_data.platform_raw_data, dict) and energy_data.platform_raw_data.get("daily_aggregated") is True
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
            "is_daily": is_daily,
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
        "expected_count": log.expected_count,
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


async def get_price_category_distribution(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    energy_type: str | None = None,
    workshop: str | None = None,
) -> dict[str, Any]:
    """获取峰谷电价分类能耗分布。"""
    categories = await repo.get_price_category_distribution(
        db, start_time, end_time, energy_type=energy_type, workshop=workshop,
    )
    grand_total = sum(c["total_value"] for c in categories)
    unit = categories[0]["unit"] if categories else ""
    return {
        "categories": categories,
        "total": grand_total,
        "unit": unit,
    }


# ── 峰谷时段规则 ──


async def list_price_periods(db: AsyncSession) -> list[dict[str, Any]]:
    return await repo.list_price_periods(db)


async def create_price_period(
    db: AsyncSession, category: str, start_hour: int, end_hour: int, months: list[int],
) -> dict[str, Any]:
    return await repo.create_price_period(db, category, start_hour, end_hour, months)


async def delete_price_period(db: AsyncSession, period_id: UUID) -> bool:
    return await repo.delete_price_period(db, period_id)


async def reset_price_periods(db: AsyncSession) -> list[dict[str, Any]]:
    return await repo.reset_price_periods(db)


# ── 预警规则 ──


async def create_alert_rule(
    db: AsyncSession, data: EnergyAlertRuleCreate
) -> EnergyAlertRule:
    create_data = data.model_dump()
    create_data["unit"] = await _get_unit_by_energy_type(db, data.energy_type)
    return await repo.create_alert_rule(db, create_data)


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
    update_data = data.model_dump(exclude_unset=True)
    # energy_type 变更时，同步 unit 为 EnergyTypeConfig 中的单位
    if "energy_type" in update_data:
        update_data["unit"] = await _get_unit_by_energy_type(db, update_data["energy_type"])
    result = await repo.update_alert_rule(
        db, rule_id, update_data
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
    workshop: str | None = None,
    workshop_not_null: bool = False,
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
        workshop=workshop,
        workshop_not_null=workshop_not_null,
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
            "processed_at": datetime.now(CST),
        },
    )
    assert result is not None
    return result


async def fill_alert_reason(
    db: AsyncSession, record_id: UUID, reason: str
) -> EnergyAlertRecord:
    """任意用户填写预警异常原因。"""
    existing = await repo.get_alert_record_by_id(db, record_id)
    if existing is None:
        raise NotFoundException("预警记录", str(record_id))
    result = await repo.update_alert_record(db, record_id, {"reason": reason})
    assert result is not None
    return result


async def approve_alert_record(
    db: AsyncSession, record_id: UUID,
) -> None:
    """管理员通过预警 → 软删除。"""
    existing = await repo.get_alert_record_by_id(db, record_id)
    if existing is None:
        raise NotFoundException("预警记录", str(record_id))
    await repo.update_alert_record(
        db, record_id, {"is_deleted": True, "status": "processed"}
    )


async def reject_alert_record(
    db: AsyncSession, record_id: UUID,
) -> EnergyAlertRecord:
    """管理员驳回预警 → status=rejected + 重新飞书推送。"""
    from app.platform.integrations.feishu.notification import send_user_card

    existing = await repo.get_alert_record_by_id(db, record_id)
    if existing is None:
        raise NotFoundException("预警记录", str(record_id))

    # 更新状态为 rejected
    result = await repo.update_alert_record(db, record_id, {"status": "rejected"})
    assert result is not None

    # 查询车间配置获取飞书推送对象
    if existing.workshop:
        ws_config = await repo.get_workshop_config_by_workshop(db, existing.workshop)
        if ws_config:
            heads = ws_config.heads or []
            open_ids = [h.get("feishu_open_id", "") for h in heads if h.get("feishu_open_id")]
            heads_mention = " ".join(
                f'<at user_id="{h.get("feishu_open_id", "")}">{h.get("name", "")}</at>'
                for h in heads if h.get("feishu_open_id")
            )

            notify_title = f"⚠️ 预警驳回 - {existing.workshop}"
            notify_content = (
                f"**{existing.workshop}**（负责人：{heads_mention}）\n"
                f"能耗预警已被管理员驳回，请重新检查异常消耗原因并更新。\n"
                f"能源类型：{existing.energy_type} | 触发值：{float(existing.trigger_value):,.2f} {existing.unit}"
            )

            for open_id in open_ids:
                success = await send_user_card(open_id, notify_title, notify_content)
                if not success:
                    logger.warning(
                        "预警驳回飞书通知失败: workshop=%s, open_id=%s",
                        existing.workshop, open_id,
                    )

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
    # 校验 alert_rule_id：若提供，必须存在且为用户手动创建的规则
    if data.alert_rule_id:
        alert_rule = await repo.get_alert_rule_by_id(db, UUID(data.alert_rule_id))
        if alert_rule is None:
            raise NotFoundException("预警规则", data.alert_rule_id)
        if alert_rule.is_system:
            raise AppException(message="不能关联系统自动生成的预警规则")
    create_data = data.model_dump()
    return await repo.create_workshop_config(db, create_data)


async def get_workshop_config(db: AsyncSession, config_id: UUID) -> EnergyWorkshopConfig:
    obj = await repo.get_workshop_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("车间预警配置", str(config_id))
    await _populate_alert_rule_name(db, [obj])
    return obj


async def list_workshop_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyWorkshopConfig], int]:
    items, total = await repo.list_workshop_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    await _populate_alert_rule_name(db, items)
    return items, total


async def _populate_alert_rule_name(
    db: AsyncSession, configs: list[EnergyWorkshopConfig]
) -> None:
    """为车间配置列表批量填充 alert_rule_name（非持久化字段）。"""
    rule_ids = [c.alert_rule_id for c in configs if c.alert_rule_id]
    if not rule_ids:
        return
    rules = await repo.get_alert_rules_by_ids(db, rule_ids)
    rule_name_map: dict[UUID, str] = {r.id: r.rule_name for r in rules}
    for c in configs:
        if c.alert_rule_id:
            c.alert_rule_name = rule_name_map.get(c.alert_rule_id)  # type: ignore[attr-defined]


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
    # 校验 alert_rule_id：若提供，必须存在且为用户手动创建的规则
    if "alert_rule_id" in update_data and update_data["alert_rule_id"] is not None:
        alert_rule = await repo.get_alert_rule_by_id(db, UUID(update_data["alert_rule_id"]))
        if alert_rule is None:
            raise NotFoundException("预警规则", update_data["alert_rule_id"])
        if alert_rule.is_system:
            raise AppException(message="不能关联系统自动生成的预警规则")
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


async def list_available_alert_rules(
    db: AsyncSession,
) -> list[EnergyAlertRule]:
    """获取可选的用户自定义预警规则列表（供车间配置下拉框使用）。"""
    return await repo.list_user_alert_rules_for_select(db)


async def list_workshop_options(
    db: AsyncSession, energy_type: str | None = None
) -> list[dict[str, str]]:
    """获取可选设备配置列表（供车间配置下拉框使用），可选按能源类型过滤。"""
    return await repo.get_device_options_by_energy_type(db, energy_type)


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
    from app.platform.integrations.feishu.notification import send_user_card

    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    configs = await repo.get_enabled_workshop_configs(db)
    if not configs:
        return {"checked": 0, "triggered": 0, "errors": 0}

    # 获取所有能源类型单位映射和显示名映射
    type_configs = await repo.list_enabled_type_configs(db)
    unit_map = {c.type_code: c.unit for c in type_configs}
    display_name_map = {c.type_code: c.display_name for c in type_configs}

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

        # 检查自定义通知时间：若设置了 notify_time，则仅在到达该时间后才评估
        if config.notify_time:
            try:
                th, tm = config.notify_time.split(":")
                target_minutes = int(th) * 60 + int(tm)
                current_minutes = now.hour * 60 + now.minute
                if current_minutes < target_minutes:
                    continue
            except (ValueError, AttributeError):
                pass  # 格式异常时不阻塞，走默认逻辑

        # 该车间下的能源类型
        workshop_combos = [
            c for c in all_combos if c["workshop"] == config.workshop
        ]
        if not workshop_combos:
            continue

        # 获取 heads 中的 feishu_open_id 并构建 @ 提及字符串
        heads = config.heads or []
        open_ids = [h.get("feishu_open_id", "") for h in heads if h.get("feishu_open_id")]
        # 飞书消息 @ 提及格式
        heads_mention = " ".join(
            f'<at user_id="{h.get("feishu_open_id", "")}">{h.get("name", "")}</at>'
            for h in heads if h.get("feishu_open_id")
        )

        # ── 用户自定义规则分支 ──
        if config.alert_rule_id:
            try:
                user_rule = await repo.get_alert_rule_by_id(db, config.alert_rule_id)
                if user_rule is None or not user_rule.is_enabled:
                    checked += 1
                else:
                    rule_energy_type = user_rule.energy_type
                    unit = user_rule.unit

                    # 检查生效时间窗口
                    if user_rule.effective_time == "custom":
                        try:
                            if user_rule.custom_time_start and user_rule.custom_time_end:
                                sh, sm = user_rule.custom_time_start.split(":")
                                eh, em = user_rule.custom_time_end.split(":")
                                start_mins = int(sh) * 60 + int(sm)
                                end_mins = int(eh) * 60 + int(em)
                                current_mins = now.hour * 60 + now.minute

                                if start_mins <= end_mins:
                                    # 不跨天：start <= current < end
                                    in_window = start_mins <= current_mins < end_mins
                                else:
                                    # 跨天（如 22:00-06:00）：current >= start 或 current < end
                                    in_window = current_mins >= start_mins or current_mins < end_mins

                                if not in_window:
                                    checked += 1
                                    continue
                        except (ValueError, AttributeError):
                            pass  # 时间格式异常时不阻塞，走全天逻辑

                    # 查重
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    existing_record = await repo.find_today_alert_record(
                        db, config.workshop, rule_energy_type, today_start
                    )
                    if existing_record is not None:
                        checked += 1
                    else:
                        # 查询昨日能耗
                        yesterday_consumption = await repo.get_workshop_daily_consumption(
                            db, config.workshop, rule_energy_type, yesterday
                        )
                        if yesterday_consumption is None or yesterday_consumption == 0:
                            checked += 1
                        else:
                            # 使用规则中的阈值类型和阈值进行判断
                            threshold_value = float(user_rule.threshold_value)
                            threshold_fn = {
                                "greater_than": lambda y, t: y > t,
                                "less_than": lambda y, t: y < t,
                                "equal": lambda y, t: y == t,
                            }.get(user_rule.threshold_type)
                            if threshold_fn is None or not threshold_fn(yesterday_consumption, threshold_value):
                                checked += 1
                            else:
                                from decimal import Decimal
                                _ = await repo.create_alert_record(db, {
                                    "rule_id": user_rule.id,
                                    "workshop": config.workshop,
                                    "energy_type": rule_energy_type,
                                    "alert_level": user_rule.alert_level,
                                    "trigger_value": Decimal(str(yesterday_consumption)),
                                    "threshold_value": user_rule.threshold_value,
                                    "unit": unit,
                                    "alert_time": now,
                                    "status": "pending",
                                })

                                # 发送飞书通知
                                display_name = display_name_map.get(rule_energy_type, rule_energy_type)
                                if user_rule.threshold_type == "less_than":
                                    excess = threshold_value - yesterday_consumption
                                elif user_rule.threshold_type == "equal":
                                    excess = abs(yesterday_consumption - threshold_value)
                                else:
                                    excess = yesterday_consumption - threshold_value
                                pct = (excess / threshold_value) * 100
                                notify_title = f"⚠️ 能耗预警 - {config.workshop}"
                                notify_content = (
                                    f"**{config.workshop}**（负责人：{heads_mention}）\n"
                                    f"{user_rule.rule_name} 阈值：{threshold_value:,.2f} {unit}"
                                    f" | 实际{display_name}：{yesterday_consumption:,.2f} {unit}\n"
                                    f"**偏移量：{excess:,.2f} {unit}（{pct:.1f}%）**"
                                )

                                for open_id in open_ids:
                                    success = await send_user_card(open_id, notify_title, notify_content)
                                    if not success:
                                        logger.warning(
                                            "车间预警飞书通知失败(自定义规则): workshop=%s, energy_type=%s, open_id=%s",
                                            config.workshop, rule_energy_type, open_id,
                                        )

                                triggered += 1
                                checked += 1
                                logger.info(
                                    "车间能耗预警触发(自定义规则): workshop=%s, energy_type=%s, "
                                    "rule=%s, threshold_type=%s, threshold_value=%.2f, yesterday=%.2f",
                                    config.workshop, rule_energy_type,
                                    user_rule.rule_name, user_rule.threshold_type,
                                    threshold_value, yesterday_consumption,
                                )
            except Exception:
                logger.exception(
                    "车间预警评估异常(自定义规则): workshop=%s", config.workshop
                )
                errors += 1
        else:
            # ── 系统规则分支（原有逻辑） ──

            # 确保系统规则存在
            energy_types = [c["energy_type"] for c in workshop_combos]
            await repo.ensure_system_rules(db, config.workshop, energy_types, unit_map)

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
                    display_name = display_name_map.get(energy_type, energy_type)
                    excess = yesterday_consumption - avg_consumption
                    pct = (excess / avg_consumption) * 100
                    notify_title = f"⚠️ 能耗预警 - {config.workshop}"
                    notify_content = (
                        f"**{config.workshop}**（负责人：{heads_mention}）\n"
                        f"日均标准：{avg_consumption:,.2f} {unit}"
                        f" | 实际{display_name}：{yesterday_consumption:,.2f} {unit}\n"
                        f"**超标量：{excess:,.2f} {unit}（+{pct:.1f}%）**"
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

        # 更新 last_checked_at（自定义规则和系统规则分支都统一在此更新）
        await repo.update_workshop_config(db, config.id, {"last_checked_at": now})

    return {"checked": checked, "triggered": triggered, "errors": errors}


# ── 能源日耗推送配置 ──

# 主能源类型固定顺序
_REPORT_ENERGY_TYPES = ["water", "electricity", "steam", "natural_gas"]

# 中文数字序数词：🥇🥈🥉
_MEDALS = ["🥇", "🥈", "🥉"]


async def create_daily_push_config(
    db: AsyncSession, data: EnergyDailyPushConfigCreate
) -> EnergyDailyPushConfig:
    create_data = data.model_dump()
    return await repo.create_daily_push_config(db, create_data)


async def get_daily_push_config(
    db: AsyncSession, config_id: UUID
) -> EnergyDailyPushConfig:
    obj = await repo.get_daily_push_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("能源总耗推送配置", str(config_id))
    # 填充设备名称
    device_ids: list[UUID] = []
    for did_attr in (
        "solar_device_id", "pressure_device_id",
        "rto1_gas_device_id", "rto2_gas_device_id",
        "rto1_elec_device_id", "rto2_elec_device_id",
    ):
        did = getattr(obj, did_attr)
        if did:
            device_ids.append(did)
    device_name_map = await repo.get_device_names_by_ids(db, device_ids)
    for attr in (
        "solar_device_id", "pressure_device_id",
        "rto1_gas_device_id", "rto2_gas_device_id",
        "rto1_elec_device_id", "rto2_elec_device_id",
    ):
        did = getattr(obj, attr)
        setattr(obj, f"{attr}_name", device_name_map.get(did) if did else None)
    return obj


async def list_daily_push_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyDailyPushConfig], int]:
    items, total = await repo.list_daily_push_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    # 填充设备名称（包括已删除设备，确保页面回显名称不丢失）
    device_ids: list[UUID] = []
    for c in items:
        for did_attr in (
            "solar_device_id", "pressure_device_id",
            "rto1_gas_device_id", "rto2_gas_device_id",
            "rto1_elec_device_id", "rto2_elec_device_id",
        ):
            did = getattr(c, did_attr)
            if did:
                device_ids.append(did)
    device_name_map = await repo.get_device_names_by_ids(db, device_ids)
    for c in items:
        for attr in (
            "solar_device_id", "pressure_device_id",
            "rto1_gas_device_id", "rto2_gas_device_id",
            "rto1_elec_device_id", "rto2_elec_device_id",
        ):
            did = getattr(c, attr)
            setattr(c, f"{attr}_name", device_name_map.get(did) if did else None)
    return items, total


async def update_daily_push_config(
    db: AsyncSession, config_id: UUID, data: EnergyDailyPushConfigUpdate
) -> EnergyDailyPushConfig:
    existing = await repo.get_daily_push_config_by_id(db, config_id)
    if existing is None:
        raise NotFoundException("能源总耗推送配置", str(config_id))
    update_data = data.model_dump(exclude_unset=True)
    result = await repo.update_daily_push_config(db, config_id, update_data)
    assert result is not None
    return result


async def delete_daily_push_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_daily_push_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("能源总耗推送配置", str(config_id))
    await repo.delete_daily_push_config(db, config_id)


async def send_daily_energy_report(
    db: AsyncSession,
    config_id: UUID,
    target_date: datetime,
) -> dict[str, Any]:
    """手动触发能源日耗推送。

    Args:
        config_id: 推送配置ID
        target_date: 要报告的日期（仅日期部分有效，时间忽略）
    Returns:
        {"success": bool, "sent_to": int, "message": str}
    """
    from app.platform.integrations.feishu.notification import send_user_card

    config = await repo.get_daily_push_config_by_id(db, config_id)
    if config is None:
        raise NotFoundException("能源总耗推送配置", str(config_id))

    target_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    prev_date = target_date - timedelta(days=1)

    # 读取能源类型配置（显示名 + 单位）
    type_configs = await repo.list_enabled_type_configs(db)
    display_name_map: dict[str, str] = {c.type_code: c.display_name for c in type_configs}
    unit_map: dict[str, str] = {c.type_code: c.unit for c in type_configs}

    # ── 报告头部 ──
    now_cst = datetime.now(CST)
    is_yesterday = target_date.date() == (now_cst - timedelta(days=1)).date()
    date_label = f"{target_date.strftime('%Y年%m月%d日')}（昨日）" if is_yesterday else target_date.strftime("%Y年%m月%d日")
    report_date_str = target_date.strftime("%Y-%m-%d")

    lines: list[str] = [
        "📊 能耗日统计分析报告",
        f"报告日期：{date_label}",
        "",
        "一、主要能耗数据",
    ]

    # 环比数据收集
    comparison_lines: list[str] = []

    section_index = 0
    for et in _REPORT_ENERGY_TYPES:
        display_name = display_name_map.get(et, et)
        unit = unit_map.get(et, "")

        # 当日总量
        today_total = await repo.get_daily_total_by_energy_type(db, et, target_date)
        if today_total is None:
            continue

        section_index += 1

        # 收集当前能源类型的所有行
        section_lines: list[str] = []
        section_lines.append(f"{section_index}. {display_name}")

        # ── 天然气：先收集 RTO 数据再写总量行 ──
        rto_data: dict[str, float | None] = {
            "rto1_gas": None, "rto2_gas": None,
            "rto1_elec": None, "rto2_elec": None,
        }
        rto_extra_lines: list[str] = []
        if et == "natural_gas":
            gas_unit = unit
            if config.rto1_gas_device_id:
                rto_data["rto1_gas"] = await repo.get_device_daily_value(db, config.rto1_gas_device_id, target_date)
            if config.rto2_gas_device_id:
                rto_data["rto2_gas"] = await repo.get_device_daily_value(db, config.rto2_gas_device_id, target_date)
            # 构建用量括号说明
            gas_parts: list[str] = []
            if rto_data["rto1_gas"] is not None and rto_data["rto1_gas"] > 0:
                gas_parts.append(f"一期 {rto_data['rto1_gas']:,.1f}")
            if rto_data["rto2_gas"] is not None and rto_data["rto2_gas"] > 0:
                gas_parts.append(f"二期 {rto_data['rto2_gas']:,.1f}")
            total_gas_line = f"- 昨日总用气：{today_total:,.1f} {gas_unit}"
            if gas_parts:
                total_gas_line += f"（{' + '.join(gas_parts)}）"

            # RTO 用气明细
            if config.rto1_gas_device_id and rto_data["rto1_gas"] is not None and rto_data["rto1_gas"] > 0:
                rto_extra_lines.append(f"- 一期RTO用气：{rto_data['rto1_gas']:,.1f} {gas_unit}")
            if config.rto2_gas_device_id and rto_data["rto2_gas"] is not None and rto_data["rto2_gas"] > 0:
                rto_extra_lines.append(f"- 二期RTO用气：{rto_data['rto2_gas']:,.1f} {gas_unit}")
            # RTO 用电明细
            if config.rto1_elec_device_id:
                rto_data["rto1_elec"] = await repo.get_device_daily_value(db, config.rto1_elec_device_id, target_date)
            if config.rto2_elec_device_id:
                rto_data["rto2_elec"] = await repo.get_device_daily_value(db, config.rto2_elec_device_id, target_date)
            elec_unit_str = unit_map.get("electricity", "kWh")
            if rto_data["rto1_elec"] is not None and rto_data["rto1_elec"] > 0:
                rto_extra_lines.append(f"- 一期RTO用电：{rto_data['rto1_elec']:,.1f} {elec_unit_str}")
            if rto_data["rto2_elec"] is not None and rto_data["rto2_elec"] > 0:
                rto_extra_lines.append(f"- 二期RTO用电：{rto_data['rto2_elec']:,.1f} {elec_unit_str}")

            section_lines.append(total_gas_line)
        else:
            section_lines.append(f"- 昨日总{display_name}：{today_total:,.1f} {unit}")

        # TOP3 部门
        top_workshops = await repo.get_daily_top_workshops(db, et, target_date, limit=3)
        if top_workshops:
            section_lines.append("- 主要消耗部门TOP3：")
            for idx, w in enumerate(top_workshops):
                section_lines.append(
                    f"  - {_MEDALS[idx]} {w['workshop']}：{w['total_value']:,.1f} {unit}（{w['percentage']}%）"
                )

        # ── 电耗：清洁能源发电 ──
        if et == "electricity":
            elec_unit = unit
            clean_total = 0.0
            clean_detail_lines: list[str] = []
            if config.solar_device_id:
                solar_val = await repo.get_device_daily_value(db, config.solar_device_id, target_date)
                if solar_val is not None and solar_val > 0:
                    clean_detail_lines.append(f"  - 光伏发电：{solar_val:,.1f} {elec_unit}")
                    clean_total += solar_val
            if config.pressure_device_id:
                pressure_val = await repo.get_device_daily_value(db, config.pressure_device_id, target_date)
                if pressure_val is not None and pressure_val > 0:
                    clean_detail_lines.append(f"  - 蒸汽差压发电：{pressure_val:,.1f} {elec_unit}")
                    clean_total += pressure_val
            if clean_detail_lines:
                section_lines.append("- 清洁能源发电：")
                section_lines.extend(clean_detail_lines)
                section_lines.append(f"  - 自发自用合计：{clean_total:,.1f} {elec_unit}")

        # ── 天然气：追加 RTO 细分行 ──
        if et == "natural_gas" and rto_extra_lines:
            section_lines.extend(rto_extra_lines)

        lines.extend(section_lines)

        # ── 环比 ──
        prev_total = await repo.get_daily_total_by_energy_type(db, et, prev_date)
        if prev_total is not None and prev_total > 0:
            change = today_total - prev_total
            change_pct = (change / prev_total) * 100
            arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
            abs_pct = abs(change_pct)
            comparison_lines.append(
                f"- 能耗类型: {display_name}, "
                f"环比变化: {'+' if change >= 0 else ''}{change:,.1f} {unit}, "
                f"变化率: {arrow} {abs_pct:.1f}%"
            )
        elif prev_total is not None:
            comparison_lines.append(
                f"- 能耗类型: {display_name}, 环比变化: 前日无数据, 变化率: —"
            )

    # ── 环比分析 section ──
    if comparison_lines:
        prev_label = prev_date.strftime("%m月%d日")
        lines.append("")
        lines.append("二、环比分析")
        lines.append("")
        lines.append(f"（与{prev_label}对比）")
        lines.append("")
        lines.extend(comparison_lines)

    # ── 拼接并发送 ──
    # 修正：如果有天然气 RTO 数据覆盖了总用气行，需要处理
    # （上面的逻辑中 lines[-4] 的索引依赖于 section 结构，改为更稳健的方式）
    content = "\n".join(lines)

    title = f"能耗日统计报告 - {report_date_str}"

    notify_users = config.notify_users or []
    success_count = 0
    for user_info in notify_users:
        open_id = user_info.get("feishu_open_id", "")
        if not open_id:
            continue
        sent = await send_user_card(open_id, title, content)
        if sent:
            success_count += 1
        else:
            logger.warning(
                "能源日耗推送飞书通知失败: open_id=%s, name=%s",
                open_id, user_info.get("name", ""),
            )

    # 更新 last_sent_at
    await repo.update_daily_push_config(db, config_id, {"last_sent_at": now_cst})

    return {
        "success": success_count > 0,
        "sent_to": success_count,
        "total_users": len(notify_users),
        "message": f"已发送给 {success_count}/{len(notify_users)} 人",
    }


async def evaluate_daily_push(db: AsyncSession) -> dict[str, Any]:
    """定时任务入口：检查所有启用的定时推送配置，到达时间后触发推送。

    与 evaluate_workshop_alerts 类似，由外部调度器周期性调用。
    """
    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    configs = await repo.get_enabled_daily_push_configs(db)
    if not configs:
        return {"checked": 0, "sent": 0}

    sent = 0
    for config in configs:
        if not config.notify_time:
            continue
        try:
            th, tm = config.notify_time.split(":")
            target_minutes = int(th) * 60 + int(tm)
            current_minutes = now.hour * 60 + now.minute
            if current_minutes < target_minutes:
                continue
        except (ValueError, AttributeError):
            continue

        # 防重复：今天已发送则跳过
        if config.last_sent_at is not None:
            if config.last_sent_at.date() == now.date():
                continue

        try:
            await send_daily_energy_report(db, config.id, yesterday)
            sent += 1
        except Exception:
            logger.exception(
                "定时推送异常: config_id=%s, name=%s", config.id, config.name
            )

    return {"checked": len(configs), "sent": sent}


# ── 氮气月度推送配置 ──


async def create_nitrogen_push_config(
    db: AsyncSession, data: EnergyNitrogenPushConfigCreate
) -> EnergyNitrogenPushConfig:
    create_data = data.model_dump()
    # JSONB 字段存字符串即可
    return await repo.create_nitrogen_push_config(db, create_data)


async def get_nitrogen_push_config(
    db: AsyncSession, config_id: UUID
) -> EnergyNitrogenPushConfig:
    obj = await repo.get_nitrogen_push_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("氮气月度推送配置", str(config_id))
    # 填充设备名称
    device_ids = obj.nitrogen_device_ids or []
    device_name_map = await repo.get_device_names_by_ids(db, device_ids)
    obj.nitrogen_device_names = [  # type: ignore[attr-defined]
        device_name_map[did] for did in device_ids if did in device_name_map
    ]
    return obj


async def list_nitrogen_push_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyNitrogenPushConfig], int]:
    items, total = await repo.list_nitrogen_push_configs(
        db, is_enabled=is_enabled, page=page, page_size=page_size
    )
    # 填充设备名称（包括已删除设备，确保页面回显名称不丢失）
    all_device_ids: list[UUID] = []
    for c in items:
        for did in c.nitrogen_device_ids or []:
            if did not in all_device_ids:
                all_device_ids.append(did)
    device_name_map = await repo.get_device_names_by_ids(db, all_device_ids)
    for c in items:
        c.nitrogen_device_names = [  # type: ignore[attr-defined]
            device_name_map.get(did, str(did))
            for did in (c.nitrogen_device_ids or [])
        ]
    return items, total


async def update_nitrogen_push_config(
    db: AsyncSession, config_id: UUID, data: EnergyNitrogenPushConfigUpdate
) -> EnergyNitrogenPushConfig:
    existing = await repo.get_nitrogen_push_config_by_id(db, config_id)
    if existing is None:
        raise NotFoundException("氮气月度推送配置", str(config_id))
    update_data = data.model_dump(exclude_unset=True)
    result = await repo.update_nitrogen_push_config(db, config_id, update_data)
    assert result is not None
    return result


async def delete_nitrogen_push_config(db: AsyncSession, config_id: UUID) -> None:
    obj = await repo.get_nitrogen_push_config_by_id(db, config_id)
    if obj is None:
        raise NotFoundException("氮气月度推送配置", str(config_id))
    await repo.delete_nitrogen_push_config(db, config_id)


async def send_nitrogen_monthly_report(
    db: AsyncSession,
    config_id: UUID,
    target_date: datetime,
) -> dict[str, Any]:
    """手动触发氮气月度进度推送。

    先用平台适配器 API 拉取目标日期的日汇总数据（保证准确性），
    写入 DB 后再查询月度累计用量生成报告。

    Args:
        config_id: 氮气推送配置ID
        target_date: 目标日期（只取年月日部分）
    """
    import calendar

    from app.platform.integrations.feishu.notification import send_user_card

    config = await repo.get_nitrogen_push_config_by_id(db, config_id)
    if config is None:
        raise NotFoundException("氮气月度推送配置", str(config_id))

    target_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    year = target_date.year
    month = target_date.month
    up_to_day = target_date.day
    total_days = calendar.monthrange(year, month)[1]

    device_ids = config.nitrogen_device_ids or []
    if not device_ids:
        return {"success": False, "sent_to": 0, "message": "未配置氮气设备，无法生成报告"}

    # 从设备配置中获取氮气的单位
    unit = "m³"
    first_device = await repo.get_device_config_by_id(db, device_ids[0])
    if first_device:
        type_config = await repo.get_type_config_by_code(db, first_device.energy_type)
        if type_config:
            unit = type_config.unit

    # ── 用 API 拉取目标日期的日汇总数据（保证准确性）──
    for did in device_ids:
        device = await repo.get_device_config_by_id(db, did)
        if device is None:
            continue
        adapter = ADAPTERS.get(device.platform_code)
        if adapter is None:
            logger.warning("氮气推送: 未找到平台适配器 %s，跳过设备 %s", device.platform_code, device.device_name)
            continue
        try:
            results = await adapter.fetch_energy_data(
                [device.platform_device_code], target_date, device.api_endpoint, is_daily=True,
            )
            for cr in results:
                if cr.device_code == device.platform_device_code:
                    value = float(cr.value)
                    # 先物理删除当天已有的逐小时数据，避免日汇总与小时数据被 SUM 重复累加
                    # （(device_config_id, timestamp) 有唯一约束，不能仅依赖 upsert 覆盖）
                    await repo.delete_hourly_data_for_device_on_date(
                        db, device.id, target_date
                    )
                    await repo.upsert_energy_data(
                        db,
                        device_config_id=device.id,
                        timestamp=cr.timestamp,
                        value=value,
                        unit=unit,
                        platform_raw_data={"daily_sum": True, "source": "nitrogen_push"},
                    )
                    logger.info(
                        "氮气推送: 拉取日汇总 device=%s day=%s value=%.2f",
                        device.device_name, target_date.strftime("%Y-%m-%d"), value,
                    )
                    break
        except NotImplementedError:
            logger.debug("平台 %s 不支持 is_daily=True，跳过日汇总拉取", device.platform_code)
        except Exception:
            logger.exception(
                "氮气推送: 拉取日汇总异常 device=%s day=%s",
                device.device_name, target_date.strftime("%Y-%m-%d"),
            )
    await db.flush()

    # ── 从 DB 查询月度累计用量 ──
    accumulated = await repo.get_monthly_nitrogen_total(
        db, device_ids, year, month, up_to_day
    )
    accumulated = accumulated or 0.0
    guaranteed = float(config.monthly_guaranteed_consumption or 0)
    remaining = guaranteed - accumulated

    # 百分比
    accumulated_pct = (accumulated / guaranteed * 100) if guaranteed > 0 else 0
    remaining_pct = (remaining / guaranteed * 100) if guaranteed > 0 else 0

    # 构建报告
    month_label = f"{year}年{month:02d}月"
    day_label = f"{month:02d}月{up_to_day:02d}日"

    lines = [
        "月度氮气进度报告",
        "📊 月度氮气用量进度报告",
        "",
        f"统计周期：{month_label}（截至{day_label}）",
        f"统计天数：{up_to_day}天 / {total_days}天",
        "",
        "---",
        "",
        "📈 用量统计",
        "",
        f"月度保底消费量：{guaranteed:,.0f} {unit} | 100%",
        f"累计实际用量：{accumulated:,.1f} {unit} | {accumulated_pct:.2f}%",
        f"剩余可用额度：{remaining:,.1f} {unit} | {remaining_pct:.2f}%",
    ]

    content = "\n".join(lines)
    report_date_str = f"{year}-{month:02d}-{up_to_day:02d}"
    title = f"月度氮气进度报告 - {report_date_str}"

    notify_users = config.notify_users or []
    success_count = 0
    for user_info in notify_users:
        open_id = user_info.get("feishu_open_id", "")
        if not open_id:
            continue
        sent = await send_user_card(open_id, title, content)
        if sent:
            success_count += 1
        else:
            logger.warning(
                "氮气月度推送飞书通知失败: open_id=%s, name=%s",
                open_id, user_info.get("name", ""),
            )

    # 更新 last_sent_at
    now_cst = datetime.now(CST)
    await repo.update_nitrogen_push_config(db, config_id, {"last_sent_at": now_cst})

    return {
        "success": success_count > 0,
        "sent_to": success_count,
        "total_users": len(notify_users),
        "message": f"已发送给 {success_count}/{len(notify_users)} 人",
    }


async def evaluate_nitrogen_push(db: AsyncSession) -> dict[str, Any]:
    """定时任务入口：检查所有启用的氮气月度推送配置，到达时间后触发推送。"""
    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    configs = await repo.get_enabled_nitrogen_push_configs(db)
    if not configs:
        return {"checked": 0, "sent": 0}

    sent = 0
    for config in configs:
        if not config.notify_time:
            continue
        try:
            th, tm = config.notify_time.split(":")
            target_minutes = int(th) * 60 + int(tm)
            current_minutes = now.hour * 60 + now.minute
            if current_minutes < target_minutes:
                continue
        except (ValueError, AttributeError):
            continue

        # 防重复：今天已发送则跳过
        if config.last_sent_at is not None:
            if config.last_sent_at.date() == now.date():
                continue

        try:
            await send_nitrogen_monthly_report(db, config.id, yesterday)
            sent += 1
        except Exception:
            logger.exception(
                "氮气月度推送异常: config_id=%s, name=%s", config.id, config.name
            )

    return {"checked": len(configs), "sent": sent}


