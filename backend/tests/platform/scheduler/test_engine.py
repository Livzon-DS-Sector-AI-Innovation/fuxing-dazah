"""SchedulerEngine 重启行为测试 — 启动后不立即触发任务。

验证：
- 首次见到任务/生成器（last_run 无记录）只登记基准时间，不执行
- 间隔任务在基准时间 + interval 后正常触发
- cron 任务在下一个触发点正常触发，且不会在重启时被补跑
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.platform.scheduler.engine import SchedulerEngine
from app.platform.scheduler.registry import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskDefinition,
    TaskGenerator,
)

TZ = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(TZ)


def _make_engine(task: TaskDefinition) -> SchedulerEngine:
    registry = SchedulerRegistry()
    registry.register_task(task)
    return SchedulerEngine(registry)


async def test_first_sight_does_not_execute_task() -> None:
    """启动后首个 tick：任何策略的任务都不立即执行。"""
    ran: list[str] = []

    async def coro() -> None:
        ran.append("run")

    task = TaskDefinition(
        name="t.interval",
        schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=60),
        coro=coro,
    )
    engine = _make_engine(task)

    await engine._maybe_run_task(task, settings=object())

    assert ran == []
    assert task.name in engine._last_run  # 已登记基准时间


async def test_interval_task_fires_after_interval() -> None:
    """基准时间 + interval 之后正常触发。"""
    ran: list[str] = []

    async def coro() -> None:
        ran.append("run")

    task = TaskDefinition(
        name="t.interval",
        schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=60),
        coro=coro,
    )
    engine = _make_engine(task)

    await engine._maybe_run_task(task, settings=object())
    assert ran == []

    # 模拟时间前进：把基准时间拨回 61 秒前
    engine._last_run[task.name] = _now() - timedelta(seconds=61)
    await engine._maybe_run_task(task, settings=object())
    assert ran == ["run"]


async def test_cron_task_not_caught_up_on_restart() -> None:
    """cron 任务重启时不补跑：首次见到只登记基准，等到下一个触发点才执行。"""
    ran: list[str] = []

    async def coro() -> None:
        ran.append("run")

    task = TaskDefinition(
        name="t.cron",
        schedule=ScheduleConfig(
            strategy=ScheduleStrategy.CRON, expression="7 0 * * *",
        ),
        coro=coro,
    )
    engine = _make_engine(task)

    await engine._maybe_run_task(task, settings=object())
    assert ran == []  # 重启瞬间（非 00:07）不执行

    # 昨天已跑过、今天 00:07 已过 → 到点触发
    engine._last_run[task.name] = _now() - timedelta(days=1)
    await engine._maybe_run_task(task, settings=object())
    assert ran == ["run"]


async def test_generator_not_scanned_on_first_sight() -> None:
    """生成器同样不在启动 tick 扫描派发。"""
    scanned: list[int] = []

    class Gen(TaskGenerator):
        name = "gen.test"
        schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL, interval_seconds=180,
        )

        async def find_due(self, session):
            scanned.append(1)
            return []

        async def execute_one(self, session, item) -> None:  # pragma: no cover
            pass

    gen = Gen()
    registry = SchedulerRegistry()
    registry.register_generator(gen)
    engine = SchedulerEngine(registry)

    await engine._maybe_run_generator(gen, settings=object())
    assert scanned == []
    assert gen.name in engine._last_run

    engine._last_run[gen.name] = _now() - timedelta(seconds=181)
    await engine._maybe_run_generator(gen, settings=object())
    assert scanned == [1]


@pytest.mark.parametrize("strategy_kwargs", [
    {"strategy": ScheduleStrategy.INTERVAL, "interval_seconds": 60},
    {"strategy": ScheduleStrategy.CRON, "expression": "* * * * *"},
    {"strategy": ScheduleStrategy.FIXED_TIME, "time_of_day": "00:05"},
])
async def test_no_strategy_fires_on_startup_tick(strategy_kwargs: dict) -> None:
    """三种策略统一约束：启动 tick 一律只登记基准时间。"""
    ran: list[str] = []

    async def coro() -> None:
        ran.append("run")

    task = TaskDefinition(name="t.all", schedule=ScheduleConfig(**strategy_kwargs), coro=coro)
    engine = _make_engine(task)

    await engine._maybe_run_task(task, settings=object())
    assert ran == []
