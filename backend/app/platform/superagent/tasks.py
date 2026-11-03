"""任务域 —— 阶段纯函数推导 / 任务创建与订阅 / 订阅直通 / 输入语义。

derive_stage 是所有观测口径的源头（红线⑥：纯函数 + 全量单测）——任何查询
路径（REST/巡检/总卡）都必须经它现算，阶段永不落库。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.superagent.models import (
    AgentInput,
    AgentTask,
    AgentTaskSubscription,
    AgentTrigger,
)
from app.platform.superagent.sources import make_disposition_step

logger = logging.getLogger(__name__)

# 阶段枚举（总卡展示文案见 STAGE_LABELS）
STAGE_DELIVERING = "delivering"    # 等交付：输入投递失败重试中
STAGE_AWAIT_ANSWER = "await_answer"  # 等回答：有 Attention
STAGE_AWAIT_ACCEPT = "await_accept"  # 等验收：最新报告 ready
STAGE_BLOCKED = "blocked"          # 受阻/失败：blocked/failed 且此后无人的消息
STAGE_QUEUED = "queued"            # 排队：无执行中 Assignment
STAGE_IDLE = "idle"                # 空闲：最新报告 waiting
STAGE_WORKING = "working"          # 其余

STAGE_ORDER: tuple[str, ...] = (
    STAGE_DELIVERING, STAGE_AWAIT_ANSWER, STAGE_AWAIT_ACCEPT,
    STAGE_BLOCKED, STAGE_QUEUED, STAGE_IDLE, STAGE_WORKING,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_DELIVERING: "投递失败",
    STAGE_AWAIT_ANSWER: "待回答",
    STAGE_AWAIT_ACCEPT: "待验收",
    STAGE_BLOCKED: "受阻·失败",
    STAGE_QUEUED: "排队",
    STAGE_IDLE: "等触发",
    STAGE_WORKING: "工作中",
}


def derive_stage(facts: dict[str, Any] | None) -> str:
    """阶段推导（纯函数；自上而下首中即用，对齐设计 §4.3 阶段表）。

    facts 约定键：
    - ``delivery_retrying``: bool   输入投递失败重试中
    - ``attention_pending``: bool   有待人工问题（Attention）
    - ``latest_report``: str|None   progress/waiting/ready/blocked/failed/dropped
    - ``human_after_report``: bool  最新报告之后是否来过人的消息
    - ``has_active_assignment``: bool
    """
    f = facts or {}
    if f.get("delivery_retrying"):
        return STAGE_DELIVERING
    if f.get("attention_pending"):
        return STAGE_AWAIT_ANSWER
    report = f.get("latest_report")
    if report == "ready":
        return STAGE_AWAIT_ACCEPT
    if report in ("blocked", "failed") and not f.get("human_after_report"):
        return STAGE_BLOCKED
    if not f.get("has_active_assignment"):
        return STAGE_QUEUED
    if report == "waiting":
        return STAGE_IDLE
    return STAGE_WORKING


# ═══════════════════════════════════════════════════════════════
# 任务创建与订阅
# ═══════════════════════════════════════════════════════════════


async def create_task(
    session: Any,
    *,
    short_name: str,
    title: str,
    executor: str,
    origin_trigger_id: uuid.UUID | None = None,
    mandate: dict[str, Any] | None = None,
    origin_thread_key: str | None = None,
) -> AgentTask:
    """开单即订阅 origin Thread（订阅直通的接线点）。"""
    task = AgentTask(
        short_name=short_name,
        title=title,
        executor=executor,
        origin_trigger_id=origin_trigger_id,
        mandate=mandate or {},
        # 程序执行器即绑定（一期无独立 Assignment 域）：True=有执行者；
        # 排队（无执行器空位）是二期 worker 域才可达的阶段
        stage_facts={"latest_report": None, "has_active_assignment": True},
        status="open",
    )
    session.add(task)
    await session.flush()

    if origin_thread_key:
        await subscribe(session, task.id, origin_thread_key)

    if origin_trigger_id:
        # 开单 Trigger 即首条输入（人的原始请求）
        session.add(AgentInput(
            task_id=task.id, trigger_id=origin_trigger_id, kind="trigger",
            payload={}, delivered_at=datetime.now(UTC),
        ))
    return task


async def subscribe(
    session: Any, task_id: uuid.UUID, thread_key: str, *, context_only: bool = False,
) -> None:
    stmt = (
        pg_insert(AgentTaskSubscription)
        .values(task_id=task_id, thread_key=thread_key, context_only=context_only)
        .on_conflict_do_nothing(index_elements=["task_id", "thread_key"])
    )
    await session.execute(stmt)


async def route_trigger_to_subscriptions(
    session: Any, trigger: AgentTrigger, *, mark_disposition: bool = True,
) -> int:
    """订阅直通：同 Thread 后续 Trigger 不经研判，直接作为 Input 送达订阅任务。

    - 订阅存在（open 任务 / ended 任务保留的订阅）→ 写 inputs + reached_task
    - ended 任务收到输入 = 唤醒（reopen，outcome 清空）
    Returns: 送达的任务数（0=无订阅，走后续研判/直派生链路）
    """
    subs = (
        await session.execute(
            select(AgentTaskSubscription).where(
                AgentTaskSubscription.thread_key == trigger.thread_key
            )
        )
    ).scalars().all()
    if not subs:
        return 0

    now = datetime.now(UTC)
    routed = 0
    for sub in subs:
        task = await session.get(AgentTask, sub.task_id)
        if task is None:
            continue
        payload = dict(trigger.payload or {})
        if sub.context_only:
            payload["_context_only"] = True  # 仅上下文（不授新权）——执行器可辨识
        session.add(AgentInput(
            task_id=task.id,
            trigger_id=trigger.id,
            kind="trigger",
            payload=payload,
            delivered_at=now,
        ))
        if task.status == "ended":
            # 唤醒：ended 任务保留订阅，人的消息可重新激活
            task.status = "open"
            task.outcome = None
            task.ended_at = None
            task.stage_facts = {**(task.stage_facts or {}), "latest_report": None}
        if trigger.human:
            from app.platform.superagent.executors import note_human_message

            note_human_message(task)  # 受阻→工作的钥匙（阶段表 human_after_report）
        routed += 1

    if mark_disposition and routed:
        trigger.disposition = list(trigger.disposition or []) + [
            make_disposition_step("reached_task", reason=f"tasks={routed}")
        ]
    return routed
