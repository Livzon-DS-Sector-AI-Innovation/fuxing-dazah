"""Energy data collection background scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.energy import repository as repo
from app.modules.energy.adapters import ADAPTERS
from app.modules.energy.models import EnergyDeviceConfig

logger = logging.getLogger(__name__)

# 中国标准时间 UTC+8
CST = timezone(timedelta(hours=8))

# 检查间隔：5 分钟
TICK_INTERVAL = 300

# 最大补采小时数：7 天
MAX_BACKFILL_HOURS = 168

stop_energy_collection_flag = asyncio.Event()


def _get_target_hours_since(last_collected_at: datetime | None) -> list[datetime]:
    """计算需要补采的整点小时列表。

    从 last_collected_at 所在整点之后，到上一个整点之间的所有整点。
    如果 last_collected_at 为 None（从未采集），只返回上一个整点。
    """
    now = datetime.now(CST)
    latest_hour = now.replace(minute=0, second=0, microsecond=0)
    if now.minute == 0:
        # 刚过整点，采集上一个整点
        latest_hour -= timedelta(hours=1)

    if last_collected_at is None:
        return [latest_hour]

    start = (
        last_collected_at.replace(minute=0, second=0, microsecond=0)
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
    # 使用第一个设备的 api_endpoint
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
                unit=cr.unit,
                platform_raw_data=cr.raw_data,
            )
            total_success += 1

    status = "success" if total_success >= expected else "partial"

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

    logger.info(
        "自动采集完成: platform=%s, status=%s, success=%d/%d",
        platform_code,
        status,
        total_success,
        expected,
    )


async def energy_collection_loop() -> None:
    """能耗数据自动采集后台循环。

    每 TICK_INTERVAL 秒检查一次，对到达 collection_interval 的设备触发采集。
    支持补采：若设备上次采集时间距今超过 collection_interval，补采缺失的整点数据。
    """
    settings = get_settings()
    if not settings.ENERGY_AUTO_COLLECT_ENABLED:
        logger.info(
            "能耗自动采集已通过配置关闭（ENERGY_AUTO_COLLECT_ENABLED=false），跳过启动"
        )
        return

    logger.info("能耗自动采集任务已启动（间隔=%d秒）", TICK_INTERVAL)

    while not stop_energy_collection_flag.is_set():
        # 每次 tick 重新读取配置，支持运行时动态开关
        if not get_settings().ENERGY_AUTO_COLLECT_ENABLED:
            logger.debug("能耗自动采集已关闭，跳过本轮 tick")
            try:
                await asyncio.wait_for(
                    stop_energy_collection_flag.wait(), timeout=TICK_INTERVAL
                )
            except TimeoutError:
                pass
            continue

        try:
            async with async_session_factory() as db:
                platforms = await repo.get_distinct_enabled_platforms(db)

                for platform_code in platforms:
                    devices = await repo.get_enabled_devices_by_platform(
                        db, platform_code
                    )
                    if not devices:
                        continue

                    # 筛选到达采集间隔的设备
                    devices_due: list[EnergyDeviceConfig] = []
                    oldest_last: datetime | None = None

                    for device in devices:
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
                                if oldest_last is None or ref_time < oldest_last:
                                    oldest_last = ref_time

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
            logger.exception("能耗自动采集循环异常")

        # 等待下一次 tick
        try:
            await asyncio.wait_for(
                stop_energy_collection_flag.wait(), timeout=TICK_INTERVAL
            )
        except TimeoutError:
            pass

    logger.info("能耗自动采集任务已停止")
