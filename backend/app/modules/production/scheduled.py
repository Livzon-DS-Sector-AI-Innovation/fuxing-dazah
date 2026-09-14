"""生产模块定时任务。

计划批次开工提醒：每天 08:31（时间窗 08:31-08:35，窗口外启动不发送）；
工序超时提醒：每 10 分钟扫描一次已物化的到期监控记录。
"""

from app.modules.production.service.reminder_service import (
    REMINDER_WINDOW_START,
    notify_batch_start_due,
)
from app.modules.production.service.timeout_service import scan_timeout_monitors
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

__all__ = [
    "BATCH_START_REMINDER_TASK",
    "EXECUTION_TIMEOUT_SCAN_TASK",
    "TIMEOUT_SCAN_TASK",
]

BATCH_START_REMINDER_TASK = TaskDefinition(
    name="production.batch_start_reminder",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        # 与 reminder_service.REMINDER_WINDOW_START 保持单一来源，避免改一处漏另一处
        time_of_day=f"{REMINDER_WINDOW_START.hour:02d}:{REMINDER_WINDOW_START.minute:02d}",
    ),
    coro=notify_batch_start_due,
    timeout_seconds=300,
    module="production",
)

EXECUTION_TIMEOUT_SCAN_TASK = TaskDefinition(
    name="production.execution_timeout_scan",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL,
        interval_seconds=10 * 60,
    ),
    coro=scan_timeout_monitors,
    timeout_seconds=120,
    module="production",
)

# 兼容早期调用方/测试中使用的通用名称。
TIMEOUT_SCAN_TASK = EXECUTION_TIMEOUT_SCAN_TASK
