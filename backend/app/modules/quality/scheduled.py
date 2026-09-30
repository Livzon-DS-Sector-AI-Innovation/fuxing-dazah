"""质量模块定时任务：接入平台统一调度引擎（cron）。

- 08:05（QUALITY_PUSH_MORNING 可配）出报早报：今日出报任务+待复核+标准文件到期提醒
- 15:00（QUALITY_PUSH_REMIND 可配）午后催办：今日出报未完成任务再提醒
"""

import os

from app.modules.quality.feishu.daily_push import (
    _parse_hhmm,
    _push_afternoon_reminder,
    _push_today_tasks,
)
from app.platform.scheduler import (
    ScheduleConfig,
    ScheduleStrategy,
    TaskDefinition,
)


def _cron_expr(env_key: str, default: tuple[int, int]) -> str:
    h, m = _parse_hhmm(os.getenv(env_key, ""), default)
    return f"{m} {h} * * *"


MORNING_PUSH_TASK = TaskDefinition(
    name="quality.morning_push",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression=_cron_expr("QUALITY_PUSH_MORNING", (8, 5)),
        timezone="Asia/Shanghai",
    ),
    coro=_push_today_tasks,
    module="quality",
)

AFTERNOON_REMIND_TASK = TaskDefinition(
    name="quality.afternoon_remind",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression=_cron_expr("QUALITY_PUSH_REMIND", (15, 0)),
        timezone="Asia/Shanghai",
    ),
    coro=_push_afternoon_reminder,
    module="quality",
)
