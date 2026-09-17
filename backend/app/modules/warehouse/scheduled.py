"""Warehouse 定时任务：每日库存快照、效期自动冻结与智能中心异常扫描。

高频查询都基于 movements 实时聚合，唯快照/异常记录需要低频兜底任务：
效期冻结每日 00:15、快照每日 00:30（北京时间）、异常扫描每日 00:45。
窗口守卫复用 is_in_snapshot_window（00:00-06:00，防 FIXED_TIME 窗口外重启
误触发）；效期冻结只扫 normal 行，靠幂等扫描代替互斥标志。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.database import async_session_factory
from app.modules.warehouse.morning_report import (
    generate_morning_report,
    is_in_briefing_window,
)
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


async def _run_scheduled_expiry_freeze() -> None:
    from app.modules.warehouse.expiry_freeze import (
        freeze_expired_stocks,
        notify_expired_freeze,
    )

    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not is_in_snapshot_window(now_cn):
        logger.info(
            "warehouse expiry freeze skipped: outside 00:00-06:00 window (now=%s)",
            now_cn.isoformat(timespec="minutes"),
        )
        return
    async with async_session_factory() as session:
        changed = await freeze_expired_stocks(session)
        await session.commit()
    notified = await notify_expired_freeze(changed)
    logger.info(
        "warehouse expiry freeze completed: frozen=%d notified=%s", len(changed), notified
    )


EXPIRY_FREEZE_TASK = TaskDefinition(
    name="warehouse.expiry_freeze",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="00:15",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_expiry_freeze,
    timeout_seconds=600,
    module="warehouse",
)


async def _run_scheduled_morning_report() -> None:
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not is_in_briefing_window(now_cn):
        logger.info(
            "warehouse morning report skipped: outside 08:00-09:00 window (now=%s)",
            now_cn.isoformat(timespec="minutes"),
        )
        return
    async with async_session_factory() as session:
        content = await generate_morning_report(
            session, now_cn.date()
        )
        await session.commit()
    logger.info("warehouse morning report generated: %s", content.get("brief_date"))


MORNING_REPORT_TASK = TaskDefinition(
    name="warehouse.morning_report",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="08:00",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_morning_report,
    timeout_seconds=600,
    module="warehouse",
)
