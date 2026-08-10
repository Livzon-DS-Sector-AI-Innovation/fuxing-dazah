"""Energy data collection background scheduler."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import Date, func, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.collect_settings import (
    CST,
    get_auto_collect_enabled,
    get_daily_collect_time,
)
from app.modules.energy.models import EnergyData, EnergyDeviceConfig, EnergyTypeConfig
from app.modules.energy.service import _get_unit_by_energy_type
from app.platform.scheduler import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskDefinition,
)

logger = logging.getLogger(__name__)

# 上次每日采集日期（防同一天重复执行）
_last_daily_collect_date: str = ""

# 每日采集检查间隔：60 秒
COLLECT_TICK_SECONDS = 60


async def _collect_device_hours(
    db: AsyncSession,
    device: EnergyDeviceConfig,
    target_day: datetime,
    unit: str,
    adapter: object,
) -> int:
    """对单台设备拉取指定天 0-23 小时的每小时数据。

    优先使用 is_daily=True 模式（一次 API 调用拿全天数据）；
    若适配器不支持则回退到逐小时并发调用。
    返回成功写入的记录数。
    """
    try:
        results = await adapter.fetch_energy_data(
            [device.platform_device_code], target_day, device.api_endpoint, is_daily=True
        )
        success_count = 0
        for cr in results:
            if cr.device_code == device.platform_device_code:
                await repo.upsert_energy_data(
                    db, device_config_id=device.id, timestamp=cr.timestamp,
                    value=cr.value, unit=unit, platform_raw_data=cr.raw_data,
                )
                success_count += 1
        return success_count
    except NotImplementedError:
        pass  # 回退到逐小时调用
    except Exception:
        logger.exception("每日采集异常(日模式): device=%s", device.device_name)
        return 0

    # ── 回退：逐小时并发采集 ──
    logger.debug("平台 %s 不支持 is_daily=True，回退逐小时并发采集", device.platform_code)

    async def _fetch_one_hour(hour: int) -> list:
        target_hour = target_day.replace(hour=hour)
        try:
            results = await adapter.fetch_energy_data(
                [device.platform_device_code], target_hour, device.api_endpoint
            )
            return [
                r for r in results
                if r.device_code == device.platform_device_code
            ]
        except Exception:
            logger.exception(
                "采集异常: device=%s, hour=%s",
                device.device_name, target_hour.strftime("%Y-%m-%d %H:00"),
            )
            return []

    import asyncio
    tasks = [_fetch_one_hour(h) for h in range(24)]
    all_results = await asyncio.gather(*tasks)

    success_count = 0
    for results in all_results:
        for cr in results:
            await repo.upsert_energy_data(
                db, device_config_id=device.id, timestamp=cr.timestamp,
                value=cr.value, unit=unit, platform_raw_data=cr.raw_data,
            )
            success_count += 1

    return success_count


async def _daily_collect_all_platforms() -> None:
    """每日统一采集：遍历所有启用设备，拉取昨天 0-23 小时的数据。"""
    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as db:
        platforms = await repo.get_distinct_enabled_platforms(db)

    total_devices = 0
    total_success = 0
    total_expected = 0

    for platform_code in platforms:
        adapter = ADAPTERS.get(platform_code)
        if adapter is None:
            logger.warning("未找到平台适配器: %s，跳过", platform_code)
            continue

        try:
            async with async_session_factory() as db:
                devices = await repo.get_enabled_devices_by_platform(db, platform_code)
                if not devices:
                    continue

                # 预加载单位映射
                unit_map: dict[str, str] = {}
                for et in {d.energy_type for d in devices}:
                    try:
                        unit_map[et] = await _get_unit_by_energy_type(db, et)
                    except Exception:
                        unit_map[et] = ""

                # 预加载采集粒度映射（按能源类型）
                granularity_map: dict[str, str] = {}
                type_configs_result = await db.execute(
                    select(EnergyTypeConfig.type_code, EnergyTypeConfig.collect_granularity).where(
                        EnergyTypeConfig.is_deleted == False,  # noqa: E712
                    )
                )
                for row in type_configs_result.all():
                    granularity_map[row.type_code] = row.collect_granularity

                platform_expected = 0
                platform_success = 0
                # 收集需要日聚合的设备（在采集完成后统一处理）
                daily_devices: list[tuple[EnergyDeviceConfig, str]] = []

                for device in devices:
                    if device.stat_role == "excluded":
                        continue
                    total_devices += 1
                    unit = unit_map.get(device.energy_type, "")
                    coll_gran = granularity_map.get(device.energy_type, "hourly")

                    if coll_gran == "daily":
                        # 采集前清理已有数据，确保重启后重新采集不会重复累加
                        # （旧日汇总记录若保留会被 SUM 一并计入，造成数据翻倍）
                        await repo.delete_hourly_data_for_device_on_date(
                            db, device.id, yesterday
                        )

                    count = await _collect_device_hours(
                        db, device, yesterday, unit, adapter
                    )
                    if coll_gran == "daily":
                        # 日汇总：采集小时数据后聚合为一条日记录
                        daily_devices.append((device, unit))
                        platform_expected += 1
                        # 不在此处累计 success_count，聚合完成后统一处理
                    else:
                        platform_success += count
                        platform_expected += 24

                # 日汇总聚合：SUM 小时数据 → 删除 → 写入一条日记录
                for device, unit in daily_devices:
                    try:
                        cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))
                        sum_result = await db.execute(
                            select(func.coalesce(func.sum(EnergyData.value), 0.0)).where(
                                EnergyData.device_config_id == device.id,
                                EnergyData.is_deleted == False,  # noqa: E712
                                cst_date == sa_cast(yesterday.date(), Date),
                            )
                        )
                        total_val = float(sum_result.scalar() or 0.0)
                        if total_val > 0:
                            await repo.delete_hourly_data_for_device_on_date(
                                db, device.id, yesterday
                            )
                            await repo.upsert_energy_data(
                                db,
                                device_config_id=device.id,
                                timestamp=yesterday,
                                value=total_val,
                                unit=unit,
                                platform_raw_data={"daily_aggregated": True},
                            )
                            platform_success += 1
                    except Exception:
                        logger.exception(
                            "日汇总聚合失败: device=%s, date=%s",
                            device.device_name, yesterday.strftime("%Y-%m-%d"),
                        )

                total_success += platform_success
                total_expected += platform_expected

                if platform_expected > 0:
                    status = (
                        "success" if platform_success >= platform_expected
                        else "partial" if platform_success > 0
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
                                "success_count": platform_success,
                                "expected_count": platform_expected,
                            },
                        )
                        await db.commit()
                    except Exception:
                        logger.exception("采集日志写入失败: platform=%s", platform_code)

        except Exception:
            logger.exception("平台 %s 每日采集异常", platform_code)

    if total_devices > 0:
        logger.info(
            "每日采集完成: date=%s, platforms=%d, devices=%d, "
            "success=%d/%d",
            yesterday.strftime("%Y-%m-%d"),
            len(platforms),
            total_devices,
            total_success,
            total_expected,
        )


async def energy_daily_collect_coro() -> None:
    """每日统一采集协程。

    由 SchedulerEngine 以 INTERVAL(60s) 策略驱动。
    当当前时间 >= 全局 daily_collect_time 时（精确到分钟），
    拉取所有启用设备昨天 0-23 小时的数据。
    同一天不重复执行。
    """
    global _last_daily_collect_date

    if not get_auto_collect_enabled():
        return

    now = datetime.now(CST)
    current_time = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    trigger_time = get_daily_collect_time()
    # 当前时间未到触发时间，跳过
    if current_time < trigger_time:
        return

    # 今天已执行过，跳过
    if _last_daily_collect_date == today_str:
        return

    _last_daily_collect_date = today_str
    logger.info("触发每日统一采集: time=%s, date=%s", trigger_time, today_str)

    try:
        await _daily_collect_all_platforms()
    except Exception:
        logger.exception("每日统一采集异常")


ENERGY_DAILY_COLLECT_TASK = TaskDefinition(
    name="energy.daily_collect",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=COLLECT_TICK_SECONDS,
    ),
    coro=energy_daily_collect_coro,
    settings_toggle_key="ENERGY_AUTO_COLLECT_ENABLED",
    module="energy",
)


# ═══════════════════════════════════════════════════════════════
# 车间能耗预警定时检查
# ═══════════════════════════════════════════════════════════════


async def energy_workshop_alert_coro() -> None:
    """检查车间能耗预警。"""
    try:
        async with async_session_factory() as db:
            from app.modules.energy.service import evaluate_workshop_alerts

            result = await evaluate_workshop_alerts(db)
            await db.commit()

            if result["checked"] > 0 or result["triggered"] > 0 or result["errors"] > 0:
                logger.info(
                    "车间能耗预警检查完成: checked=%d, triggered=%d, errors=%d",
                    result["checked"], result["triggered"], result["errors"],
                )
    except Exception:
        logger.exception("车间能耗预警检查异常")


ENERGY_WORKSHOP_ALERT_TASK = TaskDefinition(
    name="energy.workshop_alert",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=300,
    ),
    coro=energy_workshop_alert_coro,
    settings_toggle_key="ENERGY_WORKSHOP_ALERT_ENABLED",
    module="energy",
)


# ═══════════════════════════════════════════════════════════════
# 能源日耗推送定时检查
# ═══════════════════════════════════════════════════════════════


async def energy_daily_push_coro() -> None:
    """检查能源日耗推送配置。"""
    try:
        async with async_session_factory() as db:
            from app.modules.energy.service import evaluate_daily_push

            result = await evaluate_daily_push(db)
            await db.commit()

            if result["checked"] > 0 or result["sent"] > 0:
                logger.info(
                    "能源日耗推送检查完成: checked=%d, sent=%d",
                    result["checked"], result["sent"],
                )
    except Exception:
        logger.exception("能源日耗推送检查异常")


ENERGY_DAILY_PUSH_TASK = TaskDefinition(
    name="energy.daily_push",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=3600,
    ),
    coro=energy_daily_push_coro,
    settings_toggle_key="ENERGY_DAILY_PUSH_ENABLED",
    module="energy",
)


# ═══════════════════════════════════════════════════════════════
# 氮气月度推送定时检查
# ═══════════════════════════════════════════════════════════════


async def energy_nitrogen_push_coro() -> None:
    """检查氮气月度推送配置。"""
    try:
        async with async_session_factory() as db:
            from app.modules.energy.service import evaluate_nitrogen_push

            result = await evaluate_nitrogen_push(db)
            await db.commit()

            if result["checked"] > 0 or result["sent"] > 0:
                logger.info(
                    "氮气月度推送检查完成: checked=%d, sent=%d",
                    result["checked"], result["sent"],
                )
    except Exception:
        logger.exception("氮气月度推送检查异常")


ENERGY_NITROGEN_PUSH_TASK = TaskDefinition(
    name="energy.nitrogen_push",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=3600,
    ),
    coro=energy_nitrogen_push_coro,
    settings_toggle_key="ENERGY_NITROGEN_PUSH_ENABLED",
    module="energy",
)


def register_tasks(registry: SchedulerRegistry) -> None:
    """向调度引擎注册 energy 模块的所有定时任务。"""
    registry.register_task(ENERGY_DAILY_COLLECT_TASK)
    registry.register_task(ENERGY_WORKSHOP_ALERT_TASK)
    registry.register_task(ENERGY_DAILY_PUSH_TASK)
    registry.register_task(ENERGY_NITROGEN_PUSH_TASK)
