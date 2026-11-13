"""R3 运维自愈观测 REST —— 工单列表 + 全时间线回放 + 失败重试（§2.1 第 7 项）。

对齐 api/alarm_hazard_links.py 范式（管理/排障唯一面，一期无前端页）：

- 列表：executor=r3_ops_heal 任务分页倒序；R3 阶段/根因/动作从 stage_facts
  现算（阶段存 stage_facts.r3 无独立列；closed 用 task.status=ended 表达）；
  stage 筛选下推 SQL 等价条件；
- timeline：按工单聚合 origin trigger → 同 thread 后续 trigger → decisions
  → inputs → effects（dm_admin/r3_repair/r3_closure_card）→ outbox，
  任一工单完整时间线可回放（§4.7）；
- retry：open 工单重投 system input（TaskRunner 下轮重跑执行器收口核对）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundException
from app.core.response import success_response
from app.modules.safety.service.ops_selfheal_r3 import signals
from app.platform.permission.deps import RequireAdmin, RequireUser
from app.platform.superagent.models import (
    AgentDecision,
    AgentEffect,
    AgentInput,
    AgentOutboxMessage,
    AgentTask,
    AgentTaskSubscription,
    AgentTrigger,
)

ops_selfheal_router = APIRouter()


def _bj_date():
    """北京时间今日 date（窗口覆写与收口判定同口径）。"""
    from zoneinfo import ZoneInfo

    from datetime import datetime as _dt

    return _dt.now(ZoneInfo("Asia/Shanghai")).date()

#: R3 阶段 → SQL 等价条件（closed 走 status；needs_human 走 stage_facts 键）
_STAGE_CONDITIONS: dict[str, list[ColumnElement[bool]]] = {
    "closed": [AgentTask.status == "ended", AgentTask.outcome == "closed"],
    "needs_human": [
        AgentTask.status == "open",
        AgentTask.stage_facts["r3"]["stage"].astext == signals.R3_STAGE_NEEDS_HUMAN,
    ],
}


def _serialize_ticket(task: AgentTask) -> dict[str, Any]:
    r3 = signals.r3_facts(task.stage_facts)
    stage = signals.r3_stage(task.status, task.stage_facts)
    return {
        "id": str(task.id),
        "short_name": task.short_name,
        "title": task.title,
        "stage": stage,
        "stage_label": signals.R3_STAGE_LABELS.get(stage, stage),
        "status": task.status,
        "outcome": task.outcome,
        "signal": r3.get("signal"),
        "job_name": r3.get("job_name"),
        "component": r3.get("component"),
        "root_cause_class": r3.get("root_cause_class"),
        "confidence": r3.get("confidence"),
        "diag_source": r3.get("diag_source"),
        "reasoning": r3.get("reasoning"),
        "executed": r3.get("executed") or [],
        "planned": r3.get("planned") or [],
        "repair_rounds": r3.get("repair_rounds"),
        "dep_endpoints": r3.get("dep_endpoints") or [],
        "missed_days": r3.get("missed_days"),
        "backfill_summary": r3.get("backfill_summary"),
        "escalate_guidance": r3.get("escalate_guidance"),
        "first_seen_at": r3.get("first_seen_at"),
        "diag_at": r3.get("diag_at"),
        "mandate_rule": (task.mandate or {}).get("rule_id"),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "ended_at": task.ended_at.isoformat() if task.ended_at else None,
    }


@ops_selfheal_router.get("/ops-selfheal/tickets", summary="R3 自愈工单列表（分页+阶段筛选）")
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    stage: str | None = None,
    signal: str | None = None,
    job_name: str | None = None,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    if stage is not None and stage not in (*_STAGE_CONDITIONS, *signals.R3_STAGE_LABELS):
        raise AppException(
            status_code=400,
            message=f"stage 取值仅支持 {'/'.join((*_STAGE_CONDITIONS, *signals.R3_STAGE_LABELS))}",
        )
    cond: list[ColumnElement[bool]] = [AgentTask.executor == "r3_ops_heal"]
    if stage:
        if stage == "closed":
            cond.extend(_STAGE_CONDITIONS["closed"])
        elif stage in _STAGE_CONDITIONS:
            cond.extend(_STAGE_CONDITIONS[stage])
        else:  # detected/diagnosed/repairing/verify_wait → stage_facts 键等价
            cond.extend([
                AgentTask.status == "open",
                AgentTask.stage_facts["r3"]["stage"].astext == stage,
            ])
    if signal:
        cond.append(AgentTask.stage_facts["r3"]["signal"].astext == signal)
    if job_name:
        cond.append(AgentTask.stage_facts["r3"]["job_name"].astext == job_name)

    rows = (
        await db.execute(
            select(AgentTask).where(*cond)
            .order_by(AgentTask.created_at.desc())
            .limit(page_size).offset((page - 1) * page_size)
        )
    ).scalars().all()
    total = (
        await db.execute(select(func.count()).select_from(AgentTask).where(*cond))
    ).scalar_one()
    return success_response(
        data=[_serialize_ticket(r) for r in rows],
        meta={"page": page, "page_size": page_size, "total": total},
    )


async def _get_ticket_or_404(db: AsyncSession, ticket_id: str) -> AgentTask:
    try:
        tid = uuid.UUID(ticket_id)
    except ValueError as exc:
        raise NotFoundException("自愈工单不存在") from exc
    task = (
        await db.execute(
            select(AgentTask).where(AgentTask.id == tid, AgentTask.executor == "r3_ops_heal")
        )
    ).scalar_one_or_none()
    if task is None:
        raise NotFoundException("自愈工单不存在")
    return task


def _brief(payload: dict[str, Any] | None, limit: int = 400) -> dict[str, Any]:
    """payload 摘要（evidence 等大对象截断，回放可读）。"""
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[key] = value if not isinstance(value, (dict, list)) or len(str(value)) <= limit \
            else str(value)[:limit] + "…"
    return out


@ops_selfheal_router.get(
    "/ops-selfheal/tickets/{ticket_id}/timeline", summary="工单全时间线回放（trigger→decision→input→effect）",
)
async def ticket_timeline(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    task = await _get_ticket_or_404(db, ticket_id)

    # 同工单全部订阅线程的 trigger（含 origin）
    threads = (
        await db.execute(
            select(AgentTaskSubscription.thread_key).where(AgentTaskSubscription.task_id == task.id)
        )
    ).scalars().all()
    events: list[dict[str, Any]] = []

    triggers = (
        await db.execute(
            select(AgentTrigger).where(AgentTrigger.thread_key.in_(threads or ["~"]))
            .order_by(AgentTrigger.received_at)
        )
    ).scalars().all()
    trigger_ids = [t.id for t in triggers]
    for t in triggers:
        events.append({
            "kind": "trigger", "at": t.received_at.isoformat() if t.received_at else None,
            "external_id": t.external_id, "thread_key": t.thread_key,
            "signal": (t.payload or {}).get("signal"),
            "disposition": [s.get("step") for s in (t.disposition or [])],
            "payload": _brief(t.payload),
        })

    if trigger_ids:
        decisions = (
            await db.execute(
                select(AgentDecision).where(AgentDecision.trigger_id.in_(trigger_ids))
                .order_by(AgentDecision.created_at)
            )
        ).scalars().all()
        for d in decisions:
            events.append({
                "kind": "decision", "at": d.created_at.isoformat() if d.created_at else None,
                "rule_id": d.rule_id, "outcome": d.outcome, "would_accept": d.would_accept,
                "mode": d.mode, "resolution": d.resolution, "resolved_by": d.resolved_by,
            })

    inputs = (
        await db.execute(
            select(AgentInput).where(AgentInput.task_id == task.id)
            .order_by(AgentInput.created_at)
        )
    ).scalars().all()
    for i in inputs:
        events.append({
            "kind": "input", "at": i.created_at.isoformat() if i.created_at else None,
            "input_kind": i.kind, "read_at": i.read_at.isoformat() if i.read_at else None,
            "payload": _brief(i.payload),
        })

    effects = (
        await db.execute(
            select(AgentEffect).where(
                AgentEffect.kind.in_(("dm_admin", "r3_repair", "r3_closure_card")),
                (AgentEffect.payload["task_id"].astext == str(task.id))
                | (AgentEffect.dedupe_key.like(f"r3:%{task.id}%")),
            ).order_by(AgentEffect.created_at)
        )
    ).scalars().all()
    for e in effects:
        events.append({
            "kind": "effect", "at": e.created_at.isoformat() if e.created_at else None,
            "effect_kind": e.kind, "action": (e.payload or {}).get("action"),
            "dedupe_key": e.dedupe_key, "status": e.status, "attempts": e.attempts,
            "last_error": (e.last_error or "")[:200] or None,
            "payload": _brief(e.payload),
        })

    outbox = (
        await db.execute(
            select(AgentOutboxMessage).where(AgentOutboxMessage.task_id == task.id)
            .order_by(AgentOutboxMessage.seq)
        )
    ).scalars().all()
    for m in outbox:
        events.append({
            "kind": "outbox", "at": m.created_at.isoformat() if m.created_at else None,
            "purpose": m.purpose, "status": m.status, "seq": m.seq,
        })

    # 按时间稳定排序（同秒并列按 kind 权重：trigger→decision→input→effect）
    weight = {"trigger": 0, "decision": 1, "input": 2, "effect": 3, "outbox": 4}
    events.sort(key=lambda x: (x["at"] or "", weight.get(x["kind"], 9)))
    return success_response(data={
        "ticket": _serialize_ticket(task),
        "events": events,
        "event_count": len(events),
    })


@ops_selfheal_router.post(
    "/ops-selfheal/tickets/{ticket_id}/retry", summary="失败重试（重投 system input 触发收口核对重跑）",
)
async def retry_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    _admin: RequireAdmin,
) -> JSONResponse:
    task = await _get_ticket_or_404(db, ticket_id)
    if task.status != "open":
        raise AppException(status_code=409, message=f"工单已终态（{task.outcome or 'ended'}），不可重试")
    existing = (
        await db.execute(
            select(func.count()).select_from(AgentInput).where(
                AgentInput.task_id == task.id,
                AgentInput.kind == "system",
                AgentInput.read_at.is_(None),
            )
        )
    ).scalar_one()
    if existing:
        return success_response(data={"id": str(task.id), "queued": True,
                                      "note": "已有未读重试输入"})
    db.add(AgentInput(
        task_id=task.id, kind="system",
        payload={"type": "retry", "ticket_id": str(task.id), "at": datetime.now(UTC).isoformat()},
        delivered_at=datetime.now(UTC),
    ))
    await db.commit()
    return success_response(data={"id": str(task.id), "queued": True})


@ops_selfheal_router.post(
    "/ops-selfheal/tickets/{ticket_id}/extend-window",
    summary="L2 一键执行：延长该 job 当日补发窗口（进程内覆写，重启失效）",
)
async def extend_window(
    ticket_id: str,
    body: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
    *,
    _admin: RequireAdmin,
) -> JSONResponse:
    """管理员一键执行 job_window_extend（质询拍板：处方值优先+默认2h+当日1次）。

    - 只写进程内当日覆写 dict（window_override），不触碰 SCHEDULED_JOBS 声明；
    - decisions 留痕（kind=system 决策行，human operator）；结果 dm_admin 卡；
    - 失败分支：当日已改过（409）/ 工单非 open（409）/ 非工单类 job 信号（400）。
    - 判定核心与卡片回调同源（window_guard.execute_window_extend，防两处漂移）。
    """
    from app.modules.safety.service.ops_selfheal_r3.window_guard import (
        execute_window_extend,
    )

    task = await _get_ticket_or_404(db, ticket_id)
    result = await execute_window_extend(
        db, task, dict((body or {}).get("args") or {}), operator="admin",
    )
    await db.commit()
    if not result["ok"]:
        reason = result["reason"]
        status = 409 if (reason.startswith("工单已终态")
                         or reason == "already_extended_today") else 400
        cur = result.get("current_window")
        if cur:
            message = f"该 job 当日已延长过窗口（现截止 {cur}）"
        elif reason == "no_job":
            message = "该工单无关联 job（仅 job 信号工单可延长窗口）"
        else:
            message = reason
        raise AppException(status_code=status, message=message)
    return success_response(data={
        "id": str(task.id), "job_name": result["job_name"],
        "old_window": result["old_window"],
        "new_window": result["new_window"],
    })
