"""程序执行器注册制 —— Executor 协议 / Report / 注册表 / 任务运行器。

一期执行器=确定性函数（「写 Bitable+发卡」「汇总落格」类）；LLM worker
是二期的 Executor 实现之一（delegate 转正后挂进来），基座无任何特例。

Report 六值 + Attention 结构化字段——「在等人」永不从自由文本推断
（仓库 rejected concepts 教训）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.platform.superagent.models import AgentInput, AgentTask
from app.platform.superagent.tasks import derive_stage

logger = logging.getLogger(__name__)

# 执行器单轮超时（秒）；注册时可覆写
DEFAULT_EXECUTOR_TIMEOUT = 120


@dataclass(slots=True)
class Report:
    """执行器报告（阶段事实的唯一合法写入来源之一）。"""

    kind: str  # progress/waiting/ready/blocked/failed/dropped
    note: str = ""
    attention: dict[str, Any] | None = None  # 结构化提问（kind=waiting 时有效）
    output: dict[str, Any] = field(default_factory=dict)
    end_task: bool = False  # True → 任务终态（outcome=kind）

    def __post_init__(self) -> None:
        if self.kind not in ("progress", "waiting", "ready", "blocked", "failed", "dropped"):
            raise ValueError(f"invalid report kind: {self.kind}")
        if self.kind == "waiting" and self.attention is None:
            raise ValueError("waiting 报告必须带结构化 attention（禁止自由文本推断）")


Executor = Callable[[dict[str, Any], list[dict[str, Any]]], Awaitable[Report]]

_EXECUTORS: dict[str, tuple[Executor, int]] = {}


def register_executor(name: str, fn: Executor, *, timeout: int = DEFAULT_EXECUTOR_TIMEOUT) -> None:
    if name in _EXECUTORS:
        raise ValueError(f"Duplicate executor: {name}")
    _EXECUTORS[name] = (fn, timeout)


def get_executor(name: str) -> tuple[Executor, int] | None:
    return _EXECUTORS.get(name)


async def _noop_executor(task: dict[str, Any], inputs: list[dict[str, Any]]) -> Report:
    """占位执行器：消费输入并回报 waiting（一期 auto 开单/转正任务的缺省绑定；
    真实动作由 host 应用注册同名执行器覆盖语义或换绑 executor 名）。"""
    return Report(
        kind="waiting",
        note="noop executor（无注册动作）",
        attention={"question": "该任务暂无程序动作绑定，请人工跟进或注册执行器", "field": "executor"},
    )


register_executor("noop_exec", _noop_executor)


async def find_runnable_task_ids(session: Any, *, limit: int = 10) -> list[uuid.UUID]:
    """有未读输入的 open 任务。"""
    rows = (
        await session.execute(
            select(AgentTask.id)
            .join(AgentInput, AgentInput.task_id == AgentTask.id)
            .where(
                AgentTask.status == "open",
                AgentInput.read_at.is_(None),
                AgentInput.delivered_at.isnot(None),
            )
            .distinct()
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def run_task_once(session: Any, task_id: uuid.UUID) -> str:
    """领取并运行一个任务（行锁即认领；消费未读输入→执行器→落 Report）。

    Returns:
        ran / skipped（无输入或他方在办）/ no_executor
    """
    task = (
        await session.execute(
            select(AgentTask)
            .where(AgentTask.id == task_id, AgentTask.status == "open")
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if task is None:
        return "skipped"

    unread = (
        await session.execute(
            select(AgentInput)
            .where(
                AgentInput.task_id == task_id,
                AgentInput.read_at.is_(None),
                AgentInput.delivered_at.isnot(None),
            )
            .order_by(AgentInput.created_at)
        )
    ).scalars().all()
    if not unread:
        return "skipped"

    registered = get_executor(task.executor)
    if registered is None:
        logger.error("任务 %s 引用未注册执行器: %s", task_id, task.executor)
        return "no_executor"
    fn, timeout = registered

    task_dict = {
        "id": str(task.id),
        "short_name": task.short_name,
        "title": task.title,
        "mandate": dict(task.mandate or {}),
    }
    inputs = [dict(i.payload or {}) | {"_kind": i.kind} for i in unread]

    task.stage_facts = {**(task.stage_facts or {}), "has_active_assignment": True}
    try:
        report = await asyncio.wait_for(fn(task_dict, inputs), timeout=timeout)
    except TimeoutError:
        report = Report(kind="failed", note=f"executor timeout after {timeout}s")
    except Exception as exc:
        logger.exception("任务 %s 执行器异常", task_id)
        report = Report(kind="failed", note=f"{type(exc).__name__}: {exc}"[:500])

    now = datetime.now(UTC)
    for i in unread:
        i.read_at = now  # 计入会话历史才算读

    facts = dict(task.stage_facts or {})
    facts.update({
        "latest_report": report.kind,
        "latest_report_at": now.isoformat(),
        "attention_pending": report.kind == "waiting" and report.attention is not None,
        "last_attention": report.attention,
        "human_after_report": False,  # 新报告重置「此后人的消息」标记
    })
    if report.output:
        # 执行器经 Report 传回的阶段事实（执行器不自写 task 行——外层行锁下
        # 自开 session 更新同行会死锁；R3 诊断结论即走此通道，键名约定 r3）
        facts.update(report.output)
    task.stage_facts = facts

    if report.end_task or report.kind == "dropped":
        task.status = "ended"
        task.outcome = report.kind
        task.ended_at = now
    logger.info(
        "任务 %s(%s) 报告: %s（消费 %d 输入）→ 阶段 %s",
        task.short_name, task_id, report.kind, len(unread),
        derive_stage(task.stage_facts),
    )
    return "ran"


def note_human_message(task: AgentTask) -> None:
    """人的消息到达已订阅 Thread 时调用：置 human_after_report（受阻→工作的钥匙）。"""
    facts = dict(task.stage_facts or {})
    facts["human_after_report"] = True
    task.stage_facts = facts
