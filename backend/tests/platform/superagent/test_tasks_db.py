"""任务域测试 —— A 层 stage 纯函数全分支 + B 层任务链路（订阅直通/执行器/输入语义）。

derive_stage 全量单测是红线⑥：它是所有观测口径的源头。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

import app.platform.superagent.executors as executors_mod
from app.platform.superagent.executors import (
    Report,
    find_runnable_task_ids,
    register_executor,
    run_task_once,
)
from app.platform.superagent.ingest import ingest_draft
from app.platform.superagent.models import (
    AgentInput,
    AgentSource,
    AgentTask,
)
from app.platform.superagent.sources import TriggerDraft
from app.platform.superagent.tasks import (
    STAGE_AWAIT_ACCEPT,
    STAGE_AWAIT_ANSWER,
    STAGE_BLOCKED,
    STAGE_DELIVERING,
    STAGE_IDLE,
    STAGE_QUEUED,
    STAGE_WORKING,
    create_task,
    derive_stage,
    route_trigger_to_subscriptions,
    subscribe,
)

# ═══════════════════════════════════════════════════════════════
# A 层：derive_stage 全分支（红线⑥）
# ═══════════════════════════════════════════════════════════════


def test_stage_delivering_topmost() -> None:
    """等交付最优先（投递失败重试压过一切）。"""
    assert derive_stage({
        "delivery_retrying": True,
        "attention_pending": True,
        "latest_report": "ready",
    }) == STAGE_DELIVERING


def test_stage_await_answer() -> None:
    assert derive_stage({"attention_pending": True}) == STAGE_AWAIT_ANSWER


def test_stage_await_accept_on_ready() -> None:
    assert derive_stage({"latest_report": "ready", "has_active_assignment": True}) == STAGE_AWAIT_ACCEPT


def test_stage_blocked_when_no_human_after() -> None:
    assert derive_stage({
        "latest_report": "blocked", "human_after_report": False,
        "has_active_assignment": True,
    }) == STAGE_BLOCKED
    assert derive_stage({
        "latest_report": "failed", "has_active_assignment": True,
    }) == STAGE_BLOCKED


def test_stage_blocked_released_by_human_message() -> None:
    """受阻后来了人的消息 → 不再受阻（往下推导）。"""
    assert derive_stage({
        "latest_report": "blocked", "human_after_report": True,
        "has_active_assignment": True,
    }) == STAGE_WORKING


def test_stage_queued_without_assignment() -> None:
    assert derive_stage({"latest_report": "progress", "has_active_assignment": False}) == STAGE_QUEUED
    assert derive_stage({}) == STAGE_QUEUED  # 空事实兜底=排队


def test_stage_idle_on_waiting() -> None:
    assert derive_stage({"latest_report": "waiting", "has_active_assignment": True}) == STAGE_IDLE


def test_stage_working_default() -> None:
    assert derive_stage({"latest_report": "progress", "has_active_assignment": True}) == STAGE_WORKING
    assert derive_stage({"latest_report": None, "has_active_assignment": True}) == STAGE_WORKING


def test_stage_priority_delivering_over_answer() -> None:
    """等交付 > 等回答（同时命中取更前者）。"""
    assert derive_stage({"delivery_retrying": True, "attention_pending": True}) == STAGE_DELIVERING


# ═══════════════════════════════════════════════════════════════
# Report 契约
# ═══════════════════════════════════════════════════════════════


def test_report_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError):
        Report(kind="exploded")


def test_report_waiting_requires_structured_attention() -> None:
    """waiting 报告必须带结构化 attention——禁止自由文本推断「在等人」。"""
    with pytest.raises(ValueError):
        Report(kind="waiting")


# ═══════════════════════════════════════════════════════════════
# B 层：任务链路
# ═══════════════════════════════════════════════════════════════


async def _make_source(db_session) -> AgentSource:
    row = AgentSource(kind="test_echo", name=f"test.task.{uuid.uuid4().hex[:6]}",
                      config={}, enabled=True)
    db_session.add(row)
    await db_session.flush()
    return row


async def test_create_task_subscribes_origin_thread(db_session) -> None:
    task = await create_task(
        db_session, short_name="t-1", title="测试任务", executor="noop_exec",
        mandate={"policy_version": "hash1", "strength": "explicit"},
        origin_thread_key="t:hazard-1",
    )
    row = await db_session.get(AgentTask, task.id)
    assert row.status == "open"

    from app.platform.superagent.models import AgentTaskSubscription

    sub_rows = (
        await db_session.execute(
            select(AgentTaskSubscription).where(AgentTaskSubscription.task_id == task.id)
        )
    ).scalars().all()
    assert len(sub_rows) == 1
    assert sub_rows[0].thread_key == "t:hazard-1"
    assert sub_rows[0].context_only is False


async def test_subscription_direct_route_delivers_input(db_session) -> None:
    """订阅直通：同 Thread 后续 Trigger → Input 送达 + disposition reached_task；
    无 effect 直派生竞争（该源无 effect_kind）。"""
    src = await _make_source(db_session)
    task = await create_task(
        db_session, short_name="t-2", title="督办跟进", executor="noop_exec",
        origin_thread_key="t:hazard-2",
    )
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="e-1", thread_key="t:hazard-2",
        actor={"id": "u1"}, human=True, payload={"text": "已整改完成"},
    ))

    routed = await route_trigger_to_subscriptions(db_session, trigger)

    assert routed == 1
    steps = [s["step"] for s in trigger.disposition]
    assert "reached_task" in steps
    inputs = (
        await db_session.execute(select(AgentInput).where(AgentInput.task_id == task.id))
    ).scalars().all()
    assert len(inputs) == 1
    assert inputs[0].read_at is None  # 未消费
    task_row = await db_session.get(AgentTask, task.id)
    assert task_row.stage_facts.get("human_after_report") is True  # 人的消息标记


async def test_ended_task_wakeup_via_subscription(db_session) -> None:
    """ended 任务保留订阅：同 Thread 新 Trigger → 唤醒（reopen）。"""
    src = await _make_source(db_session)
    task = await create_task(
        db_session, short_name="t-3", title="可唤醒", executor="noop_exec",
        origin_thread_key="t:hazard-3",
    )
    task.status = "ended"
    task.outcome = "dropped"
    task.ended_at = datetime.now(UTC)
    await db_session.flush()

    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="e-2", thread_key="t:hazard-3", actor={"id": "u2"}, human=True,
    ))
    routed = await route_trigger_to_subscriptions(db_session, trigger)
    assert routed == 1

    task_row = await db_session.get(AgentTask, task.id)
    assert task_row.status == "open"
    assert task_row.outcome is None


async def test_no_subscription_returns_zero(db_session) -> None:
    src = await _make_source(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="e-3", thread_key="t:nowhere",
    ))
    assert await route_trigger_to_subscriptions(db_session, trigger) == 0


async def test_run_task_once_consumes_inputs_and_records_report(db_session) -> None:
    """执行器运行：消费未读输入（read_at 置位）+ Report 落 stage_facts。"""
    reports: list[Report] = []

    async def echo_exec(task: dict, inputs: list[dict]) -> Report:
        reports.append(Report(kind="ready", note=f"got {len(inputs)}"))
        return Report(kind="ready", note=f"got {len(inputs)}")

    executors_mod._EXECUTORS.pop("test_echo_exec", None)
    register_executor("test_echo_exec", echo_exec)
    try:
        task = await create_task(
            db_session, short_name="t-4", title="执行一次", executor="test_echo_exec",
        )
        db_session.add(AgentInput(
            task_id=task.id, kind="system", payload={"hello": 1},
            delivered_at=datetime.now(UTC),
        ))
        await db_session.flush()

        ids = await find_runnable_task_ids(db_session)
        assert task.id in ids
        outcome = await run_task_once(db_session, task.id)
        assert outcome == "ran"

        row = await db_session.get(AgentTask, task.id)
        assert row.stage_facts["latest_report"] == "ready"
        assert derive_stage(row.stage_facts) == STAGE_AWAIT_ACCEPT  # ready → 待验收
        inputs = (
            await db_session.execute(select(AgentInput).where(AgentInput.task_id == task.id))
        ).scalars().all()
        assert all(i.read_at is not None for i in inputs)
        assert len(reports) == 1
    finally:
        executors_mod._EXECUTORS.pop("test_echo_exec", None)


async def test_run_task_once_waiting_sets_attention(db_session) -> None:
    async def asker(task: dict, inputs: list[dict]) -> Report:
        return Report(
            kind="waiting", note="等答复",
            attention={"question": "整改期限是哪天？", "field": "deadline"},
        )

    executors_mod._EXECUTORS.pop("test_ask_exec", None)
    register_executor("test_ask_exec", asker)
    try:
        task = await create_task(
            db_session, short_name="t-5", title="要提问", executor="test_ask_exec",
        )
        db_session.add(AgentInput(task_id=task.id, kind="system", payload={},
                                  delivered_at=datetime.now(UTC)))
        await db_session.flush()
        await run_task_once(db_session, task.id)
        row = await db_session.get(AgentTask, task.id)
        assert derive_stage(row.stage_facts) == STAGE_AWAIT_ANSWER
        assert row.stage_facts["last_attention"]["field"] == "deadline"
    finally:
        executors_mod._EXECUTORS.pop("test_ask_exec", None)


async def test_run_task_dropped_ends_task(db_session) -> None:
    async def dropper(task: dict, inputs: list[dict]) -> Report:
        return Report(kind="dropped", note="不再需要")

    executors_mod._EXECUTORS.pop("test_drop_exec", None)
    register_executor("test_drop_exec", dropper)
    try:
        task = await create_task(
            db_session, short_name="t-6", title="会放弃", executor="test_drop_exec",
        )
        db_session.add(AgentInput(task_id=task.id, kind="system", payload={},
                                  delivered_at=datetime.now(UTC)))
        await db_session.flush()
        await run_task_once(db_session, task.id)
        row = await db_session.get(AgentTask, task.id)
        assert row.status == "ended"
        assert row.outcome == "dropped"
    finally:
        executors_mod._EXECUTORS.pop("test_drop_exec", None)


async def test_run_task_executor_exception_is_failed_report(db_session) -> None:
    async def boom(task: dict, inputs: list[dict]) -> Report:
        raise RuntimeError("executor exploded")

    executors_mod._EXECUTORS.pop("test_boom_exec", None)
    register_executor("test_boom_exec", boom)
    try:
        task = await create_task(
            db_session, short_name="t-7", title="会炸", executor="test_boom_exec",
        )
        db_session.add(AgentInput(task_id=task.id, kind="system", payload={},
                                  delivered_at=datetime.now(UTC)))
        await db_session.flush()
        outcome = await run_task_once(db_session, task.id)
        assert outcome == "ran"  # 异常被吸收为 failed Report，不炸运行器
        row = await db_session.get(AgentTask, task.id)
        assert row.stage_facts["latest_report"] == "failed"
        assert derive_stage(row.stage_facts) == STAGE_BLOCKED
    finally:
        executors_mod._EXECUTORS.pop("test_boom_exec", None)


async def test_subscribe_idempotent(db_session) -> None:
    task = await create_task(db_session, short_name="t-8", title="幂等订阅",
                             executor="noop_exec")
    await subscribe(db_session, task.id, "t:sub-1")
    await subscribe(db_session, task.id, "t:sub-1", context_only=True)
    from app.platform.superagent.models import AgentTaskSubscription

    rows = (
        await db_session.execute(
            select(AgentTaskSubscription).where(AgentTaskSubscription.task_id == task.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_noop_executor_registered_and_waits(db_session) -> None:
    """noop_exec 已注册：消费输入回报 waiting（带结构化 attention）。"""
    task = await create_task(db_session, short_name="t-noop", title="占位",
                             executor="noop_exec")
    from datetime import UTC, datetime

    db_session.add(AgentInput(task_id=task.id, kind="system", payload={},
                              delivered_at=datetime.now(UTC)))
    await db_session.flush()
    outcome = await run_task_once(db_session, task.id)
    assert outcome == "ran"
    row = await db_session.get(AgentTask, task.id)
    assert derive_stage(row.stage_facts) == STAGE_AWAIT_ANSWER


async def test_context_only_subscription_marks_input(db_session) -> None:
    """context_only 订阅：Input 带 _context_only 标记（不授新权——执行器辨识）。"""
    src = AgentSource(kind="test_echo", name=f"test.ctx.{uuid.uuid4().hex[:6]}",
                      config={}, enabled=True)
    db_session.add(src)
    await db_session.flush()
    task = await create_task(db_session, short_name="t-ctx", title="上下文",
                             executor="noop_exec")
    await subscribe(db_session, task.id, "t:ctx-1", context_only=True)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="ctx-1", thread_key="t:ctx-1",
    ))
    await route_trigger_to_subscriptions(db_session, trigger)
    inputs = (
        await db_session.execute(select(AgentInput).where(AgentInput.task_id == task.id))
    ).scalars().all()
    assert len(inputs) == 1
    assert inputs[0].payload.get("_context_only") is True
