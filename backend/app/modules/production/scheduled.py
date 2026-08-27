"""生产模块定时任务。

计划批次开工提醒：每天 08:31（时间窗 08:31-08:35，窗口外启动不发送）。
"""

from app.modules.production.service.reminder_service import (
    REMINDER_WINDOW_START,
    notify_batch_start_due,
)
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

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
