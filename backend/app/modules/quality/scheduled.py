"""质量模块定时任务：接入平台统一调度引擎（cron）。

- 08:05（QUALITY_PUSH_MORNING 可配）出报早报：今日出报任务+待复核+标准文件到期提醒
- 15:00（QUALITY_PUSH_REMIND 可配）午后催办：今日出报未完成任务再提醒
"""

import os

from app.modules.quality.feishu.daily_push import (
    _parse_hhmm,
    _push_afternoon_reminder,
    _push_material_alerts,
    _push_stocktake_reminder,
    _push_today_tasks,
)
from app.platform.scheduler import (
    ScheduleConfig,
    SchedulerRegistry,
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

STOCKTAKE_REMIND_TASK = TaskDefinition(
    name="quality.stocktake_remind",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression="0 9 25 * *",
        timezone="Asia/Shanghai",
    ),
    coro=_push_stocktake_reminder,
    module="quality",
)

MATERIAL_ALERT_TASK = TaskDefinition(
    name="quality.material_alert",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression=_cron_expr("QUALITY_PUSH_MATERIAL", (8, 15)),
        timezone="Asia/Shanghai",
    ),
    coro=_push_material_alerts,
    module="quality",
)


def register_tasks(registry: SchedulerRegistry) -> None:
    """聚合注册质量模块全部定时任务，main.py 一行挂载（仿 energy 模式）。"""
    registry.register_task(MORNING_PUSH_TASK)
    registry.register_task(AFTERNOON_REMIND_TASK)
    registry.register_task(MATERIAL_ALERT_TASK)
    registry.register_task(STOCKTAKE_REMIND_TASK)
