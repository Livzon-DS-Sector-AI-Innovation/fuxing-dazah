"""Warehouse 定时任务：每日库存快照。

高频查询都基于 movements 实时聚合，唯快照需要低频兜底任务：
每日 00:30（北京时间）生成当日快照，供驾驶舱环比/趋势使用。
窗口守卫与互斥逻辑见 snapshot 模块（宁夏仓实测教训：FIXED_TIME
任务在窗口外重启会误触发；全量任务需防重入）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

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
