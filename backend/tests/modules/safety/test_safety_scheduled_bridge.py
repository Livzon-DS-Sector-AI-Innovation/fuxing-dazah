"""2-C 桥接迁移：桥接任务派发语义 + hazard_direct 单轮化守卫。

接缝：
- ``safety_bridge_tick``（判定 + 派生执行，不阻塞引擎）
- ``_hazard_single_round``（开关/错开/overlap/连续失败告警）
- ``register_safety_tasks``（5 任务注册形状）

语义对照基线在 test_scheduler_semantics.py（状态机断言迁移前后不变）。
依据：.scratch/safety-agent-optimization-p2/spec.md 2-C 节。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

# ── 桥接任务形状与注册 ───────────────────────────────────────────


def test_register_safety_tasks_registers_six() -> None:
    from app.modules.safety.scheduled import register_safety_tasks
    from app.platform.scheduler import SchedulerRegistry

    registry = SchedulerRegistry()
    register_safety_tasks(registry)
    names = set(registry._tasks.keys())
    assert names == {
        "safety.scheduler_bridge",
        "safety.hazard_ai_poll",
        "safety.hazard_review_poll",
        "safety.hazard_supervision_poll",
        "safety.hazard_bulletin_watch",
        "safety.telemetry_collect",
    }


def test_bridge_task_shape() -> None:
    from app.modules.safety.scheduled import SAFETY_SCHEDULER_BRIDGE_TASK

    assert SAFETY_SCHEDULER_BRIDGE_TASK.schedule.interval_seconds == 30
    assert SAFETY_SCHEDULER_BRIDGE_TASK.module == "safety"


# ── 桥接 tick：判定 + 派发 ──────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_bridge_tasks():
    from app.modules.safety import scheduled

    scheduled._BRIDGE_TASKS.clear()
    yield
    scheduled._BRIDGE_TASKS.clear()


def test_bridge_tick_dispatches_due_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety import scheduled, scheduler

    job = {"name": "测试任务", "hour": 8, "minute": 0, "enabled": True}
    dispatched: list[str] = []

    async def fake_load():
        return [dict(job)]

    async def fake_should_run(j, today):
        return True

    async def fake_guarded(j):
        dispatched.append(j["name"])

    monkeypatch.setattr(scheduler, "_load_effective_jobs", fake_load)
    monkeypatch.setattr(scheduler, "_should_run", fake_should_run)
    monkeypatch.setattr(scheduler, "_run_scheduled_job_guarded", fake_guarded)

    asyncio.run(scheduled.safety_bridge_tick())
    # 派生的任务需要事件循环让一步
    async def _drain():
        while scheduled._BRIDGE_TASKS:
            await asyncio.sleep(0)

    asyncio.run(_drain())
    assert dispatched == ["测试任务"]


def test_bridge_tick_returns_fast_despite_long_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """业务任务耗时 2s，tick 必须立刻返回（派生不 await，防阻塞引擎）。"""
    from app.modules.safety import scheduled, scheduler

    async def fake_load():
        return [{"name": "慢任务", "hour": 0, "minute": 0, "enabled": True}]

    async def fake_should_run(j, today):
        return True

    async def slow_guarded(j):
        await asyncio.sleep(2)

    monkeypatch.setattr(scheduler, "_load_effective_jobs", fake_load)
    monkeypatch.setattr(scheduler, "_should_run", fake_should_run)
    monkeypatch.setattr(scheduler, "_run_scheduled_job_guarded", slow_guarded)

    started = time.monotonic()
    asyncio.run(scheduled.safety_bridge_tick())
    assert time.monotonic() - started < 0.5
    # 清理慢任务，避免泄漏到其它用例
    for task in list(scheduled._BRIDGE_TASKS):
        task.cancel()


def test_drain_awaits_spawned_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety import scheduled, scheduler

    done: list[str] = []

    async def fake_load():
        return [{"name": "任务A", "hour": 0, "minute": 0, "enabled": True}]

    async def fake_should_run(j, today):
        return True

    async def quick_guarded(j):
        await asyncio.sleep(0.01)
        done.append(j["name"])

    monkeypatch.setattr(scheduler, "_load_effective_jobs", fake_load)
    monkeypatch.setattr(scheduler, "_should_run", fake_should_run)
    monkeypatch.setattr(scheduler, "_run_scheduled_job_guarded", quick_guarded)

    async def scenario():
        await scheduled.safety_bridge_tick()
        await scheduled.drain_safety_scheduled_tasks(timeout=5)

    asyncio.run(scenario())
    assert done == ["任务A"]
    assert not scheduled._BRIDGE_TASKS


# ── hazard_direct 单轮守卫 ───────────────────────────────────────


def _reset_round_state(monkeypatch: pytest.MonkeyPatch, *, staggered: bool = True):
    from app.modules.safety import scheduled as sched

    monkeypatch.setattr(sched, "_RUNNING", set())
    monkeypatch.setattr(sched, "_CONSECUTIVE_FAILURES", {})
    # 错开判定：staggered=True 视为启动已久（错开已过）
    anchor = time.monotonic() - 10_000 if staggered else time.monotonic()
    monkeypatch.setattr(sched, "_STARTED_AT", anchor)
    return sched


def test_hazard_round_disabled_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    sched = _reset_round_state(monkeypatch)
    called: list[int] = []

    async def round_fn():
        called.append(1)

    asyncio.run(
        sched._hazard_single_round("ai", "测试", 0, lambda: False, round_fn)
    )
    assert called == []


def test_hazard_round_stagger_skips_until_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    sched = _reset_round_state(monkeypatch, staggered=False)  # 刚启动
    called: list[int] = []

    async def round_fn():
        called.append(1)

    asyncio.run(
        sched._hazard_single_round("ai", "测试", 150, lambda: True, round_fn)
    )
    assert called == []  # 错开窗口内跳过，等下个 interval


def test_hazard_round_overlap_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """上轮未完时再次触发 → 跳过（单实例约束）。"""
    sched = _reset_round_state(monkeypatch)
    runs: list[int] = []
    release = asyncio.Event()

    async def round_fn():
        runs.append(1)
        if len(runs) == 1:
            await release.wait()  # 第一轮挂住
        return SimpleNamespace(failed=0)

    async def scenario():
        import asyncio as aio

        t1 = aio.create_task(
            sched._hazard_single_round("ai", "测试", 0, lambda: True, round_fn)
        )
        await aio.sleep(0.01)  # 让第一轮进入 RUNNING
        await sched._hazard_single_round("ai", "测试", 0, lambda: True, round_fn)
        release.set()
        await t1

    asyncio.run(scenario())
    assert len(runs) == 1


def test_hazard_round_consecutive_failure_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    """连续失败达到阈值(3) → 告警一次并重置。"""
    sched = _reset_round_state(monkeypatch)

    from app.modules.safety.service.hazard_direct import alert

    alerts: list[tuple[str, int]] = []

    async def fake_notify(label, consecutive, error):
        alerts.append((label, consecutive))

    monkeypatch.setattr(alert, "notify_rounds_exceeded", fake_notify)

    async def failing_round():
        return SimpleNamespace(failed=2, failures=[{"record_id": "r1", "reason": "x"}])

    async def scenario():
        for _ in range(3):
            await sched._hazard_single_round(
                "ai", "隐患AI分析轮询", 0, lambda: True, failing_round,
            )

    asyncio.run(scenario())
    assert alerts == [("隐患AI分析轮询", 3)]
    assert sched._CONSECUTIVE_FAILURES["ai"] == 0  # 告警后重置


def test_hazard_poll_tasks_use_nonblocking_dispatch() -> None:
    """审查修复回归：hazard 三任务挂派发器而非整轮协程（防引擎内联阻塞）。"""
    from app.modules.safety import scheduled

    assert scheduled.HAZARD_AI_POLL_TASK.coro is scheduled._dispatch_hazard_ai_round
    assert (
        scheduled.HAZARD_REVIEW_POLL_TASK.coro is scheduled._dispatch_hazard_review_round
    )
    assert (
        scheduled.HAZARD_SUPERVISION_POLL_TASK.coro
        is scheduled._dispatch_hazard_supervision_round
    )
    # 派发器应瞬时返回，引擎侧超时不再是整轮上限的守卫位
    assert scheduled.HAZARD_AI_POLL_TASK.timeout_seconds < scheduled._HAZARD_TIMEOUT


def test_hazard_dispatch_returns_before_round_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整轮在后台任务执行，派发协程不等待整轮完成（超时上限由 wait_for 保留）。"""
    from app.modules.safety import scheduled

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_round():
        started.set()
        await release.wait()

    monkeypatch.setattr(scheduled, "_run_hazard_ai_round", slow_round)

    async def scenario():
        await scheduled._dispatch_hazard_ai_round()  # 应立即返回，不等整轮
        await asyncio.wait_for(started.wait(), timeout=1)
        assert scheduled._BACKGROUND_ROUNDS, "后台任务应持有引用"
        release.set()
        await asyncio.sleep(0.05)
        assert not scheduled._BACKGROUND_ROUNDS, "完成后应释放引用"

    asyncio.run(asyncio.wait_for(scenario(), timeout=3))
