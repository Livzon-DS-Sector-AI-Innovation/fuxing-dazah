"""Energy data collection background scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.collect_settings import (
    CST,
    get_auto_collect_enabled,
)
from app.modules.energy.models import EnergyDeviceConfig
from app.modules.energy.service import _collect_daily_summary, _get_unit_by_energy_type
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

# 日汇总采集检查间隔：60 秒
DAILY_CHECK_INTERVAL = 60


async def _daily_collect_check() -> None:
    """检查是否有设备需要在当前时间触发日汇总采集。

    每天检查一次：当 HH:MM 匹配设备的 daily_collect_time 时，
    对 collection_interval >= 1440 的设备补采缺失的日汇总记录。
    """
    now = datetime.now(CST)
    current_time = now.strftime("%H:%M")
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as db:
        platforms = await repo.get_distinct_enabled_platforms(db)

        for platform_code in platforms:
            try:
                devices = await repo.get_enabled_devices_by_platform(db, platform_code)
            except Exception:
                continue

            # 筛选当前时间触发的按天设备
            triggered: list[EnergyDeviceConfig] = []
            for device in devices:
                if not device.daily_collect_time:
                    continue
                if device.collection_interval < 1440:
                    continue
                if device.daily_collect_time > current_time:  # 还没到触发时间
                    continue
                triggered.append(device)

            if not triggered:
                continue

            logger.info(
                "触发日汇总采集: platform=%s, devices=%d, time=%s",
                platform_code, len(triggered), current_time,
            )

            success_count = 0
            newly_collected = 0
            for device in triggered:
                days = device.collection_interval // 1440
                for d in range(days):
                    target_day = today - timedelta(days=d + 1)
                    try:
                        exists = await repo.daily_record_exists(
                            db, device.id, target_day
                        )
                    except Exception:
                        continue
                    if exists:
                        logger.debug(
                            "日汇总已存在: device=%s, day=%s",
                            device.device_name, target_day.strftime("%Y-%m-%d"),
                        )
                        success_count += 1  # 已存在也算成功
                        continue

                    async with async_session_factory() as collect_db:
                        try:
                            await _collect_daily_summary(collect_db, device, target_day)
                            await collect_db.commit()
                            success_count += 1
                            newly_collected += 1
                        except Exception:
                            logger.exception(
                                "日汇总采集异常: device=%s, day=%s",
                                device.device_name,
                                target_day.strftime("%Y-%m-%d"),
                            )

            # 写入采集日志（仅当有新采集时记录）
            if newly_collected > 0:
                total_expected = sum(d.collection_interval // 1440 for d in triggered)
                status = (
                    "success" if success_count >= total_expected
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
                            "device_count": total_expected,
                            "success_count": newly_collected,
                        },
                    )
                    await db.commit()
                except Exception:
                    logger.exception("日汇总采集日志写入失败: platform=%s", platform_code)

# 检查间隔：5 分钟（调度器唤醒频率，实际采集频率由每台设备的 collection_interval 控制）
TICK_INTERVAL = 300

# 最大补采小时数：7 天
MAX_BACKFILL_HOURS = 168

stop_energy_collection_flag = asyncio.Event()


def _get_target_hours_since(last_data_timestamp: datetime | None) -> list[datetime]:
    """计算需要补采的整点小时列表。

    从 last_data_timestamp 所在整点之后，到上一个整点之间的所有整点。
    如果 last_data_timestamp 为 None（从未采集），只返回上一个整点。
    """
    now = datetime.now(CST)
    latest_hour = now.replace(minute=0, second=0, microsecond=0)
    if now.minute == 0:
        # 刚过整点，采集上一个整点
        latest_hour -= timedelta(hours=1)

    if last_data_timestamp is None:
        return [latest_hour]

    start = (
        last_data_timestamp.replace(minute=0, second=0, microsecond=0)
        + timedelta(hours=1)
    )
    if start > latest_hour:
        return []

    hours: list[datetime] = []
    current = start
    while current <= latest_hour:
        hours.append(current)
        current += timedelta(hours=1)

    if len(hours) > MAX_BACKFILL_HOURS:
        logger.warning(
            "补采小时数过多 (%d)，截断至最近 %d 小时",
            len(hours),
            MAX_BACKFILL_HOURS,
        )
        hours = hours[-MAX_BACKFILL_HOURS:]

    return hours


async def _do_collect(
    db: AsyncSession,
    platform_code: str,
    devices: list[EnergyDeviceConfig],
    target_hours: list[datetime],
) -> None:
    """对指定平台的设备执行采集并入库（在已有 DB 会话中操作）。"""
    adapter = ADAPTERS.get(platform_code)
    if adapter is None:
        logger.warning("未找到平台适配器: %s，跳过采集", platform_code)
        return

    device_codes = [d.platform_device_code for d in devices]
    device_map = {d.platform_device_code: d for d in devices}

    # 预加载能源类型单位映射
    unit_map: dict[str, str] = {}
    unique_types = {d.energy_type for d in devices}
    for et in unique_types:
        try:
            unit_map[et] = await _get_unit_by_energy_type(db, et)
        except Exception:
            unit_map[et] = ""  # 采集时找不到单位不阻断流程

    # 取设备配置的 api_endpoint：优先第一个非空值，所有设备一致时直接使用
    api_endpoints = {
        d.api_endpoint.strip() for d in devices if d.api_endpoint and d.api_endpoint.strip()
    }
    if len(api_endpoints) > 1:
        logger.warning(
            "平台 %s 下存在多个不同的 api_endpoint: %s，将使用 %s",
            platform_code,
            api_endpoints,
            devices[0].api_endpoint,
        )
    api_endpoint = devices[0].api_endpoint

    total_success = 0
    expected = len(devices) * len(target_hours)

    for target_hour in target_hours:
        try:
            collect_results = await adapter.fetch_energy_data(
                device_codes, target_hour, api_endpoint
            )
        except NotImplementedError:
            logger.debug("平台 %s 适配器尚未实现，跳过自动采集", platform_code)
            return
        except Exception:
            logger.exception(
                "平台 %s 采集 %s 异常", platform_code, target_hour
            )
            continue

        for cr in collect_results:
            device = device_map.get(cr.device_code)
            if device is None:
                continue
            await repo.upsert_energy_data(
                db,
                device_config_id=device.id,
                timestamp=cr.timestamp,
                value=cr.value,
                unit=unit_map.get(device.energy_type, ""),
                platform_raw_data=cr.raw_data,
            )
            total_success += 1

            # 零值采集告警（所有能源类型，不阻断流程）
            if cr.value == 0:
                logger.warning(
                    "能耗设备零值采集: device=%s(%s), energy_type=%s, "
                    "timestamp=%s, value=0, raw_data=%s",
                    device.device_name,
                    device.platform_device_code,
                    device.energy_type,
                    cr.timestamp.isoformat(),
                    cr.raw_data,
                )

            # 时间区间校验：采集时间与数据时间差值不应超过 24h
            now_cst = datetime.now(CST)
            time_gap_minutes = abs(
                (now_cst - cr.timestamp).total_seconds() / 60
            )
            if time_gap_minutes > 24 * 60:
                logger.warning(
                    "采集时间与数据时间间隔过大: device=%s(%s), gap=%.0f分钟, "
                    "data_timestamp=%s",
                    device.device_name,
                    device.platform_device_code,
                    time_gap_minutes,
                    cr.timestamp.isoformat(),
                )

    status = "success" if total_success >= expected else "partial"

    try:
        await repo.create_collect_log(
            db,
            {
                "platform_code": platform_code,
                "collect_time": datetime.now(CST),
                "status": status,
                "device_count": expected,
                "success_count": total_success,
            },
        )
    except Exception:
        logger.exception(
            "平台 %s 采集日志写入失败（不影响能耗数据）", platform_code
        )

    logger.info(
        "自动采集完成: platform=%s, status=%s, success=%d/%d",
        platform_code,
        status,
        total_success,
        expected,
    )


async def energy_collection_loop() -> None:
    """能耗数据自动采集后台循环。

    根据运行时设置（可通过 API 动态调整）决定是否启用及检查间隔。
    各平台独立事务，一个平台采集失败不影响其他平台。
    """
    # 初始状态从配置读取（env / .env）
    initial_enabled = get_auto_collect_enabled()
    if not initial_enabled:
        logger.info(
            "能耗自动采集已通过配置关闭（ENERGY_AUTO_COLLECT_ENABLED=false），跳过启动"
        )
        # 但仍然进入循环，等待运行时开启
    else:
        logger.info("能耗自动采集任务已启动")

    while not stop_energy_collection_flag.is_set():
        # 每次 tick 检查运行时设置，支持前端动态开关
        if not get_auto_collect_enabled():
            try:
                await asyncio.wait_for(
                    stop_energy_collection_flag.wait(), timeout=30
                )
            except TimeoutError:
                pass
            continue

        # ── 小时级采集 ──
        try:
            async with async_session_factory() as db:
                platforms = await repo.get_distinct_enabled_platforms(db)
            # 释放查询会话，各平台独立采集

            for platform_code in platforms:
                try:
                    async with async_session_factory() as db:
                        devices = await repo.get_enabled_devices_by_platform(
                            db, platform_code
                        )
                        if not devices:
                            continue

                        # 筛选到达采集间隔的设备（跳过按天设备，由 _daily_collect_check 单独处理）
                        devices_due: list[EnergyDeviceConfig] = []
                        oldest_last: datetime | None = None

                        for device in devices:
                            # 按天设备不参与小时级采集
                            if device.daily_collect_time and device.collection_interval >= 1440:
                                continue
                            latest = await repo.get_latest_energy_data(db, device.id)
                            if latest is None:
                                devices_due.append(device)
                            else:
                                ref_time = latest.collected_at
                                elapsed = (
                                    datetime.now(CST) - ref_time
                                ).total_seconds() / 60
                                if elapsed >= device.collection_interval:
                                    devices_due.append(device)
                                    # 用数据时间戳计算补采小时（而非 collected_at）
                                    if oldest_last is None or latest.timestamp < oldest_last:
                                        oldest_last = latest.timestamp

                        if not devices_due:
                            continue

                        target_hours = _get_target_hours_since(oldest_last)
                        if not target_hours:
                            continue

                        logger.info(
                            "触发自动采集: platform=%s, devices=%d, hours=%d",
                            platform_code,
                            len(devices_due),
                            len(target_hours),
                        )

                        await _do_collect(
                            db, platform_code, devices_due, target_hours
                        )
                        await db.commit()
                except Exception:
                    logger.exception(
                        "平台 %s 自动采集循环异常，跳过本轮继续下一个平台",
                        platform_code,
                    )

        except Exception:
            logger.exception("能耗自动采集循环异常")

        # 等待下一次 tick：每 60s 检查日汇总，每 300s 检查小时级采集
        for i in range(TICK_INTERVAL // DAILY_CHECK_INTERVAL):
            try:
                await asyncio.wait_for(
                    stop_energy_collection_flag.wait(), timeout=DAILY_CHECK_INTERVAL
                )
                return  # stop flag set
            except TimeoutError:
                pass

            # 每个 TICK_INTERVAL 周期仅在第一次迭代检查日汇总（避免每分钟重复查询）
            if i == 0 and get_auto_collect_enabled():
                try:
                    await _daily_collect_check()
                except Exception:
                    logger.exception("日汇总采集检查异常")

    logger.info("能耗自动采集任务已停止")


# ═══════════════════════════════════════════════════════════════
# 车间能耗预警定时检查
# ═══════════════════════════════════════════════════════════════


async def energy_workshop_alert_coro() -> None:
    """每分钟检查一次，当时间匹配 ENERGY_WORKSHOP_ALERT_TIME 时执行预警评估。

    由 SchedulerEngine 以 INTERVAL(60s) 策略驱动。
    防重复：通过 DB 中 EnergyWorkshopConfig.last_checked_at 的日期判定，
    同一天不重复检查。
    """
    from datetime import datetime

    from app.core.config import get_settings
    from app.core.database import async_session_factory

    settings = get_settings()
    if not settings.ENERGY_WORKSHOP_ALERT_ENABLED:
        return

    # 解析配置的 HH:MM 时间
    try:
        h, m = settings.ENERGY_WORKSHOP_ALERT_TIME.split(":")
        target_hour, target_minute = int(h), int(m)
    except (ValueError, AttributeError):
        logger.warning("ENERGY_WORKSHOP_ALERT_TIME 格式无效: %s", settings.ENERGY_WORKSHOP_ALERT_TIME)
        return

    now = datetime.now(CST)
    if now.hour != target_hour or now.minute != target_minute:
        return

    try:
        async with async_session_factory() as db:
            from app.modules.energy.service import evaluate_workshop_alerts

            result = await evaluate_workshop_alerts(db)
            await db.commit()

            logger.info(
                "车间能耗预警检查完成: checked=%d, triggered=%d, errors=%d",
                result["checked"], result["triggered"], result["errors"],
            )
    except Exception:
        logger.exception("车间能耗预警检查异常")


ENERGY_WORKSHOP_ALERT_TASK = TaskDefinition(
    name="energy.workshop_alert",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=60,
    ),
    coro=energy_workshop_alert_coro,
    settings_toggle_key="ENERGY_WORKSHOP_ALERT_ENABLED",
    module="energy",
)
