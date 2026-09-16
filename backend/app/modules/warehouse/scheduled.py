"""Warehouse 定时任务：每日库存快照与智能中心异常扫描。

高频查询都基于 movements 实时聚合，唯快照/异常记录需要低频兜底任务：
快照每日 00:30（北京时间），异常扫描每日 00:45。
窗口守卫与互斥逻辑见 snapshot/intelligence 模块（宁夏仓实测教训：
FIXED_TIME 任务在窗口外重启会误触发；全量任务需防重入）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.database import async_session_factory
from app.modules.warehouse.snapshot import (
    is_in_snapshot_window,
    run_stock_daily_snapshot,
)
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)


async def _run_scheduled_stock_snapshot() -> None:
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not is_in_snapshot_window(now_cn):
        logger.info(
            "warehouse stock snapshot skipped: outside 00:00-06:00 window (now=%s)",
            now_cn.isoformat(timespec="minutes"),
        )
        return
    await run_stock_daily_snapshot()


async def _run_scheduled_alert_scan() -> None:
    from app.modules.warehouse.intelligence import run_intelligence_scan

    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not is_in_snapshot_window(now_cn):
        logger.info(
            "warehouse alert scan skipped: outside 00:00-06:00 window (now=%s)",
            now_cn.isoformat(timespec="minutes"),
        )
        return
    async with async_session_factory() as session:
        counts = await run_intelligence_scan(session)
        await session.commit()
    logger.info(
        "warehouse alert scan completed: %s", counts
    )


STOCK_DAILY_SNAPSHOT_TASK = TaskDefinition(
    name="warehouse.stock_daily_snapshot",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="00:30",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_stock_snapshot,
    timeout_seconds=1800,
    module="warehouse",
)

INTELLIGENCE_SCAN_TASK = TaskDefinition(
    name="warehouse.intelligence_scan",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="00:45",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_alert_scan,
    timeout_seconds=1800,
    module="warehouse",
)
