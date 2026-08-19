"""Energy data collection background scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import Date, func, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.collect_settings import (
    CST,
    get_auto_collect_enabled,
    get_default_daily_collect_time,
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

# 上次每日采集日期（本进程内防长采集期间重复触发）
_last_daily_collect_date: date | None = None

# 每日采集检查间隔：60 秒
COLLECT_TICK_SECONDS = 60

# 各平台 API 并发上限（避免冲垮三方接口）
_PLATFORM_SEMAPHORES: dict[str, asyncio.Semaphore] = {
    "zhiheng": asyncio.Semaphore(2),     # 智恒分页 API 较重
    "platform_b": asyncio.Semaphore(5),  # 智能电气 6 设备×24h 回退
}


def _get_platform_semaphore(platform_code: str) -> asyncio.Semaphore:
    """获取平台并发信号量，未配置的平台默认上限 3。"""
    if platform_code not in _PLATFORM_SEMAPHORES:
        _PLATFORM_SEMAPHORES[platform_code] = asyncio.Semaphore(3)
    return _PLATFORM_SEMAPHORES[platform_code]


async def _collect_device_hours(
    db: AsyncSession,
    device: EnergyDeviceConfig,
    target_day: datetime,
    unit: str,
    adapter: object,
    *,
    use_daily_mode: bool = False,
) -> int:
    """对单台设备拉取指定天 0-23 小时的每小时数据。

    日汇总设备（use_daily_mode=True）优先使用 is_daily=True 一次拿全天，
    适配器不支持时回退到逐小时并发调用。
    小时设备直接走逐小时并发调用。

    返回成功写入的记录数。
    所有 adapter.fetch_energy_data 调用受平台级 Semaphore 管控。
    """
    sem = _get_platform_semaphore(device.platform_code)

    if use_daily_mode:
        try:
            async with sem:
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

    # ── 逐小时并发采集 ──
    logger.debug("平台 %s 逐小时并发采集: device=%s", device.platform_code, device.device_name)

    async def _fetch_one_hour(hour: int) -> list:
        target_hour = target_day.replace(hour=hour)
        try:
            async with sem:
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


async def _collect_platform_devices(
    platform_code: str,
    yesterday: datetime,
    collect_time: datetime,
) -> dict | None:
    """采集单个平台下所有设备（设备并发，各自独立 session）。

    三阶段：① 预清理日汇总设备旧数据 → ② 并发采集所有设备 →
    ③ 日汇总聚合 + 写采集日志。
    """
    adapter = ADAPTERS.get(platform_code)
    if adapter is None:
        logger.warning("未找到平台适配器: %s，跳过", platform_code)
        return None

    async with async_session_factory() as db:
        devices = await repo.get_enabled_devices_by_platform(db, platform_code)
        if not devices:
            return {
                "platform_code": platform_code,
                "device_count": 0,
                "success_count": 0,
                "expected_count": 0,
                "status": "success",
            }

        # 预加载元数据
        unit_map: dict[str, str] = {}
        for et in {d.energy_type for d in devices}:
            try:
                unit_map[et] = await _get_unit_by_energy_type(db, et)
            except Exception:
                unit_map[et] = ""

        granularity_map: dict[str, str] = {}
        type_configs_result = await db.execute(
            select(EnergyTypeConfig.type_code, EnergyTypeConfig.collect_granularity).where(
                EnergyTypeConfig.is_deleted == False,  # noqa: E712
            )
        )
        for row in type_configs_result.all():
            granularity_map[row.type_code] = row.collect_granularity

    # ── 阶段 ①：预清理日汇总设备旧数据 ──
    async with async_session_factory() as db:
        for device in devices:
            if device.stat_role == "excluded":
                continue
            if granularity_map.get(device.energy_type, "hourly") == "daily":
                await repo.delete_hourly_data_for_device_on_date(
                    db, device.id, yesterday
                )
        await db.commit()

    # ── 阶段 ②：所有设备并发采集（各用独立 session）──
    async def _collect_one(device: EnergyDeviceConfig, unit: str):
        async with async_session_factory() as db:
            try:
                is_daily = granularity_map.get(device.energy_type, "hourly") == "daily"
                count = await _collect_device_hours(
                    db, device, yesterday, unit, adapter, use_daily_mode=is_daily
                )
                await db.commit()
                return device, unit, count
            except Exception:
                logger.exception(
                    "采集异常: device=%s, day=%s",
                    device.device_name,
                    yesterday.strftime("%Y-%m-%d"),
                )
                return device, unit, 0

    active = [
        (d, unit_map.get(d.energy_type, ""))
        for d in devices
        if d.stat_role != "excluded"
    ]
    device_results = await asyncio.gather(
        *[_collect_one(d, u) for d, u in active]
    )

    # ── 阶段 ③：日汇总聚合 + 写采集日志 ──
    async with async_session_factory() as db:
        platform_expected = 0
        platform_success = 0
        daily_devices: list[tuple[EnergyDeviceConfig, str, int]] = []

        for device, unit, count in device_results:
            coll_gran = granularity_map.get(device.energy_type, "hourly")
            if coll_gran == "daily":
                daily_devices.append((device, unit, count))
                platform_expected += 1
            else:
                platform_success += count
                platform_expected += 24

        for device, unit, count in daily_devices:
            try:
                cst_date = func.date(
                    func.timezone("Asia/Shanghai", EnergyData.timestamp)
                )
                sum_result = await db.execute(
                    select(
                        func.coalesce(func.sum(EnergyData.value), 0.0)
                    ).where(
                        EnergyData.device_config_id == device.id,
                        EnergyData.is_deleted == False,  # noqa: E712
                        cst_date == sa_cast(yesterday.date(), Date),
                    )
                )
                total_val = float(sum_result.scalar() or 0.0)
                # 采集到数据即写日汇总并计成功（真实值可能为 0）；
                # 未采集到数据（count=0）时 SUM 也会是 0，不能用 >=0 误判成功。
                if count > 0:
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
                    device.device_name,
                    yesterday.strftime("%Y-%m-%d"),
                )

        status = (
            "success"
            if platform_success >= platform_expected
            else "partial"
            if platform_success > 0
            else "failed"
        )

        if platform_expected > 0:
            try:
                await repo.create_collect_log(
                    db,
                    {
                        "platform_code": platform_code,
                        "collect_time": collect_time,
                        "status": status,
                        "device_count": len(devices),
                        "success_count": platform_success,
                        "expected_count": platform_expected,
                    },
                )
                await db.commit()
            except Exception:
                logger.exception("采集日志写入失败: platform=%s", platform_code)

    return {
        "platform_code": platform_code,
        "status": status,
        "device_count": len(devices),
        "success_count": platform_success,
        "expected_count": platform_expected,
    }


async def _daily_collect_all_platforms() -> None:
    """每日统一采集：所有平台并发 + 平台内所有设备并发。"""
    now = datetime.now(CST)
    yesterday = (now - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async with async_session_factory() as db:
        platforms = await repo.get_distinct_enabled_platforms(db)

    if not platforms:
        return

    tasks = [
        _collect_platform_devices(pc, yesterday, now) for pc in platforms
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    total_devices = 0
    total_success = 0
    total_expected = 0
    for r in results:
        if isinstance(r, Exception):
            logger.exception("平台采集异常: %s", r)
            continue
        if r is None:
            continue
        total_devices += r["device_count"]
        total_success += r["success_count"]
        total_expected += r["expected_count"]

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
    当天已采过（存在采集日志）则不重复执行，重启 / 多 worker 下也可靠。
    """
    global _last_daily_collect_date

    if not get_auto_collect_enabled():
        return

    now = datetime.now(CST)
    current_time = now.strftime("%H:%M")
    today = now.date()

    async with async_session_factory() as db:
        # 用户配置的触发时间持久化在 DB，未配置时回退默认值
        trigger_time = await repo.get_collect_setting_value(
            db, repo.COLLECT_SETTING_DAILY_COLLECT_TIME
        ) or get_default_daily_collect_time()

        # 当前时间未到触发时间，跳过
        if current_time < trigger_time:
            return

        # 本进程内已触发过（防长采集期间本进程重复触发）
        if _last_daily_collect_date == today:
            return

        # 跨进程 / 重启去重：当天已产生采集日志则跳过
        if await repo.has_collect_log_for_date(db, today):
            _last_daily_collect_date = today
            return

    _last_daily_collect_date = today  # 先置位，防长采集期间重复
    logger.info("触发每日统一采集: time=%s, date=%s", trigger_time, today)

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
