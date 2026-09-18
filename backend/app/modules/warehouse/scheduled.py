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
        result = await freeze_expired_stocks(session)
        await session.commit()
    notified = await notify_expired_freeze(result["changed"])
    logger.info(
        "warehouse expiry freeze completed: frozen=%d skipped=%d notified=%s",
        len(result["changed"]), len(result["skipped"]), notified,
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


async def _run_push_center_tick() -> None:
    """推送订阅中心单泵轮询（V3.0 分期A）：读 DB 任务配置执行到期推送。

    到期判断/窗口守卫/互斥在引擎内实现（push_center.engine），
    本包装只负责会话与提交；未到期任务静默跳过，tick 本身无窗口限制。
    顺带做确认单过期清扫（确认门生命周期兜底，同泵复用）。
    """
    from app.modules.warehouse.confirm_request import expire_stale_requests
    from app.modules.warehouse.push_center.engine import run_due_tasks

    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    async with async_session_factory() as session:
        results = await run_due_tasks(session, now_cn)
        expired = await expire_stale_requests(session)
        await session.commit()
    if results:
        logger.info(
            "warehouse push tick: %s",
            [(r.task_name, r.status) for r in results],
        )
    if expired:
        logger.info("warehouse confirm requests expired: %d", expired)


PUSH_CENTER_TICK_TASK = TaskDefinition(
    name="warehouse.push_center_tick",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL,
        interval_seconds=60,
    ),
    coro=_run_push_center_tick,
    timeout_seconds=300,
    module="warehouse",
)


async def _run_scheduled_qc_scan() -> None:
    """QC 请验放行闭环扫描（V3.0 分期B，设计 §4.1）：每 60min 拉取
    material_receipt 未闭环记录，镜像 QC 状态并驱动提醒/建门/生成。

    拉取/幂等/去重在 qc_flow 内实现；本包装只负责会话与提交。
    """
    from app.modules.warehouse.qc_flow import run_qc_scan

    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
    async with async_session_factory() as session:
        summary = await run_qc_scan(session, now_cn)
        await session.commit()
    if summary["pulled"]:
        logger.info("warehouse qc scan: %s", summary)


QC_SCAN_TASK = TaskDefinition(
    name="warehouse.qc_scan",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL,
        interval_seconds=3600,
    ),
    coro=_run_scheduled_qc_scan,
    timeout_seconds=600,
    module="warehouse",
)
