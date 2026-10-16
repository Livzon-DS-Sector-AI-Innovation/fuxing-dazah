"""安全模块定时任务 → 平台 SchedulerEngine 注册（2-C 桥接式迁移）。

桥接语义（保 DB 配置驱动 + 引擎执行）：注册一个 30s interval 桥接任务，
每轮做原 ``scheduled_task_loop`` 一个 tick 的工作——重读 ``_load_effective_jobs``
（DB 配置改 30s 内生效）→ ``_should_run`` 判定（时间窗 >= 触发、当日去重、
失败退避重试，状态机在 scheduler_job_runs）→ **派生** ``_run_scheduled_job_guarded``
执行（绝不 await，防 45 分钟 AI 日报阻塞引擎单循环）。17 个任务业务函数、
留痕（scheduler_task_run_log）、失败告警、群→私顺序信号零改动。

hazard_direct ①②③④ 四个常驻轮询协程转为引擎 interval 任务：单轮执行 +
overlap 守卫（上轮未完跳过）+ 启动错开（不动 sleep，到点前先跳过），
窗口逻辑（④ 周四 13-18 点）在 ``run_bulletin_watch_once`` 内自查。

语义对照基线：tests/modules/safety/test_scheduler_semantics.py（迁移前后均须绿）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskDefinition

logger = logging.getLogger(__name__)

# 启动锚点（错开判定基准）与单轮执行状态
_STARTED_AT = time.monotonic()
_RUNNING: set[str] = set()
_CONSECUTIVE_FAILURES: dict[str, int] = {}

# 桥接派生的业务任务句柄（关闭时 drain 用）
_BRIDGE_TASKS: set[asyncio.Task] = set()


async def bootstrap_safety_scheduler() -> None:
    """启动引导（原 scheduled_task_loop 启动段）：播种默认任务配置 + 直读缓存预热。"""
    try:
        from app.modules.safety.service.scheduler_config import (
            seed_default_task_targets,
        )

        await seed_default_task_targets()
    except Exception:
        logger.exception("默认任务配置播种失败（忽略，继续启动）")

    from app.modules.safety.scheduler import _warm_direct_query_caches

    asyncio.create_task(_warm_direct_query_caches())


async def safety_bridge_tick() -> None:
    """桥接任务单轮：等价原主循环一个 tick（判定 + 派发后立即返回）。"""
    from app.modules.safety import scheduler

    today = date.today()
    jobs = await scheduler._load_effective_jobs()
    for job in jobs:
        if await scheduler._should_run(job, today):
            task = asyncio.create_task(scheduler._run_scheduled_job_guarded(job))
            _BRIDGE_TASKS.add(task)
            task.add_done_callback(_BRIDGE_TASKS.discard)


async def drain_safety_scheduled_tasks(timeout: float = 60.0) -> None:
    """关闭时等待在跑业务任务收尾（原主循环 shutdown 语义的工程化版本）。"""
    if _BRIDGE_TASKS:
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(_BRIDGE_TASKS), return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "安全定时任务收尾等待超时(%ss)，剩余 %d 个任务随进程退出",
                timeout, len(_BRIDGE_TASKS),
            )


SAFETY_SCHEDULER_BRIDGE_TASK = TaskDefinition(
    name="safety.scheduler_bridge",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL,
        interval_seconds=30,
        timezone="Asia/Shanghai",
    ),
    coro=safety_bridge_tick,
    timeout_seconds=60,
    module="safety",
)


# ═══════════════════════════════════════════════════════════════
# hazard_direct ①②③④：常驻轮询协程 → 单轮 interval 任务
# ═══════════════════════════════════════════════════════════════


def _round_failure_detail(result: Any) -> str:
    """把「N 条失败」细化为「N 条失败（record: reason；）」。

    连续失败告警原先只写「2 条失败」，排障时必须翻日志才能知道原因
    （2026-09-11 事故：原因其实是 AI 客户端缺 base_url 属性）——故把本轮
    前 3 条失败原因带进告警（迁自 hazard_direct/loop.py 同名，2-C 调度归一）。
    """
    detail = f"{getattr(result, 'failed', 0)} 条失败"
    failures = getattr(result, "failures", None) or []
    parts = [
        f"{f.get('record_id', '?')}: {f.get('reason', '')}"
        for f in failures[:3]
    ]
    if parts:
        detail += "（" + "；".join(parts) + "）"
    if len(failures) > 3:
        detail += f" 等 {len(failures)} 条"
    return detail[:400]


async def _hazard_single_round(
    key: str,
    label: str,
    stagger_seconds: int,
    enabled: Callable[[], bool],
    round_fn: Callable[[], Awaitable[Any]],
) -> None:
    """单轮执行：开关 → 启动错开 → overlap 守卫 → 执行 + 连续失败告警。

    错开用「启动锚点已过的时长」判定（不动 sleep，不阻塞引擎 tick）；
    上轮未完直接跳过本轮（interval 到点即再试），Bitable 单表并发写约束不变。
    """
    if not enabled():
        return
    if (time.monotonic() - _STARTED_AT) < stagger_seconds:
        return  # 启动错开窗口内先不跑，等下个 interval 触发
    if key in _RUNNING:
        logger.warning("hazard_direct %s 上轮未完，跳过本次触发", label)
        return

    from app.modules.safety.service.hazard_direct import config
    from app.modules.safety.service.hazard_direct.alert import notify_rounds_exceeded

    _RUNNING.add(key)
    error = ""
    try:
        result = await round_fn()
        failed = getattr(result, "failed", 0)
        if failed == 0:
            _CONSECUTIVE_FAILURES[key] = 0
            return
        _CONSECUTIVE_FAILURES[key] = _CONSECUTIVE_FAILURES.get(key, 0) + 1
        error = _round_failure_detail(result)
    except Exception as exc:
        _CONSECUTIVE_FAILURES[key] = _CONSECUTIVE_FAILURES.get(key, 0) + 1
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("hazard_direct %s 单轮异常", label)
    finally:
        _RUNNING.discard(key)

    if _CONSECUTIVE_FAILURES[key] >= config.alert_after_rounds():
        await notify_rounds_exceeded(label, _CONSECUTIVE_FAILURES[key], error)
        _CONSECUTIVE_FAILURES[key] = 0  # 告警后重置，避免每轮重复轰炸


async def _run_hazard_ai_round() -> None:
    """① 隐患AI分析（间隔默认 300s，无错开）。"""
    from app.modules.safety.service.hazard_direct import config
    from app.modules.safety.service.hazard_direct.ai_analysis import (
        run_ai_analysis_round,
    )

    await _hazard_single_round(
        "ai", "隐患AI分析轮询", 0, config.ai_poll_enabled, run_ai_analysis_round,
    )


async def _run_hazard_review_round() -> None:
    """② AI整改审核（相对 ① 错开半周期）。"""
    from app.modules.safety.service.hazard_direct import config
    from app.modules.safety.service.hazard_direct.review import run_review_round

    await _hazard_single_round(
        "review", "隐患整改审核轮询", config.review_stagger_seconds(),
        config.review_poll_enabled, run_review_round,
    )


async def _run_hazard_supervision_round() -> None:
    """③ 督办等级计算（相对 ① 错开四分之一周期，只回写多维表格）。"""
    from app.modules.safety.service.hazard_direct import config
    from app.modules.safety.service.hazard_direct.supervision import (
        run_supervision_round,
    )

    await _hazard_single_round(
        "supervision", "督办等级计算轮询", config.supervision_stagger_seconds(),
        config.supervision_poll_enabled, run_supervision_round,
    )


async def _run_hazard_bulletin_watch() -> None:
    """④ 督办通报值守（周四 13:00-18:00 窗口在 run_bulletin_watch_once 内自查）。"""
    from app.modules.safety.service.hazard_direct import config
    from app.modules.safety.service.hazard_direct.bulletin_watch import (
        run_bulletin_watch_once,
    )

    await _hazard_single_round(
        "bulletin_watch", "督办通报值守轮询", 30,
        config.bulletin_watch_enabled, run_bulletin_watch_once,
    )


def _hazard_poll_interval() -> int:
    from app.modules.safety.service.hazard_direct import config

    return config.poll_interval_seconds()


def _bulletin_watch_interval() -> int:
    from app.modules.safety.service.hazard_direct import config

    return config.bulletin_watch_interval_seconds()


_HAZARD_TIMEOUT = 45 * 60  # 对齐 scheduler.TASK_TIMEOUT（AI 分析单轮上限）

# hazard 整轮的后台任务句柄（持引用防 GC，完成即移除）
_BACKGROUND_ROUNDS: set[asyncio.Task] = set()


def _round_done(task: asyncio.Task) -> None:
    _BACKGROUND_ROUNDS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("hazard 后台轮询任务异常退出", exc_info=exc)


def _dispatch_hazard_round(round_coro: Awaitable, label: str) -> None:
    """整轮派发到后台任务后立即返回（审查修复：防引擎单循环阻塞）。

    平台引擎对任务协程是内联 await（engine._maybe_run_task），协程直接跑
    整轮 AI 分析（单轮上限 _HAZARD_TIMEOUT）会把引擎单循环挂起整轮时长，
    期间全平台任务（含仓储推送、桥接 tick）停摆——与桥接任务「绝不 await」
    同一纪律。超时上限由 wait_for 在后台任务内保留；重叠防护仍由
    _hazard_single_round 的 per-key 锁负责（上轮未完跳过本次触发）。
    """
    task = asyncio.create_task(
        asyncio.wait_for(round_coro, timeout=_HAZARD_TIMEOUT), name=label
    )
    _BACKGROUND_ROUNDS.add(task)
    task.add_done_callback(_round_done)


async def _dispatch_hazard_ai_round() -> None:
    _dispatch_hazard_round(_run_hazard_ai_round(), "safety.hazard_ai_poll.round")


async def _dispatch_hazard_review_round() -> None:
    _dispatch_hazard_round(_run_hazard_review_round(), "safety.hazard_review_poll.round")


async def _dispatch_hazard_supervision_round() -> None:
    _dispatch_hazard_round(
        _run_hazard_supervision_round(), "safety.hazard_supervision_poll.round"
    )


HAZARD_AI_POLL_TASK = TaskDefinition(
    name="safety.hazard_ai_poll",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=_hazard_poll_interval(),
    ),
    coro=_dispatch_hazard_ai_round,
    # 引擎侧超时约束的是派发器（瞬时返回）；整轮上限在 _dispatch_hazard_round
    timeout_seconds=60,
    module="safety",
)

HAZARD_REVIEW_POLL_TASK = TaskDefinition(
    name="safety.hazard_review_poll",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=_hazard_poll_interval(),
    ),
    coro=_dispatch_hazard_review_round,
    timeout_seconds=60,
    module="safety",
)

HAZARD_SUPERVISION_POLL_TASK = TaskDefinition(
    name="safety.hazard_supervision_poll",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=_hazard_poll_interval(),
    ),
    coro=_dispatch_hazard_supervision_round,
    timeout_seconds=60,
    module="safety",
)

HAZARD_BULLETIN_WATCH_TASK = TaskDefinition(
    name="safety.hazard_bulletin_watch",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL,
        interval_seconds=_bulletin_watch_interval(),
    ),
    coro=_run_hazard_bulletin_watch,
    timeout_seconds=300,
    module="safety",
)

_SAFETY_TASKS: tuple[TaskDefinition, ...] = (
    SAFETY_SCHEDULER_BRIDGE_TASK,
    HAZARD_AI_POLL_TASK,
    HAZARD_REVIEW_POLL_TASK,
    HAZARD_SUPERVISION_POLL_TASK,
    HAZARD_BULLETIN_WATCH_TASK,
)


def register_safety_tasks(registry) -> None:
    """安全模块 5 个任务注册进平台引擎（main.py 启动接线，对齐仓储模式）。"""
    for task in _SAFETY_TASKS:
        registry.register_task(task)
