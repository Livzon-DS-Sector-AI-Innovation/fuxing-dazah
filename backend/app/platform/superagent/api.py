"""Super-agent 底座 REST 观测面（/api/v1/platform/superagent/*）。

读端点 RequireUser；变更端点（decisions promote/dismiss 等）随切片 1c 落位。
一期只读观测 + 底座自证（冒烟②验收=Trigger/Thread/disposition 在 REST 可查）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.platform.permission.deps import RequireAdmin, RequireUser
from app.platform.superagent.models import AgentSource, AgentThread, AgentTrigger

router = APIRouter()


def _disposition_filter(disposition: str | None):
    """disposition 追加式过滤：任一步骤命中即返回（JSONB 包含查询）。"""
    if not disposition:
        return None
    from sqlalchemy import literal
    from sqlalchemy.dialects.postgresql import JSONB

    return AgentTrigger.disposition.op("@>")(
        literal(json.dumps([{"step": disposition}]), type_=JSONB)
    )


@router.get("/triggers", summary="Trigger 列表（可按处置步骤/Thread 过滤）")
async def list_triggers(
    disposition: str | None = None,
    source_name: str | None = None,
    thread_key: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    limit = max(1, min(limit, 200))
    base = select(AgentTrigger, AgentSource.name).join(
        AgentSource, AgentTrigger.source_id == AgentSource.id
    )
    cond = _disposition_filter(disposition)
    if cond is not None:
        base = base.where(cond)
    if source_name:
        base = base.where(AgentSource.name == source_name)
    if thread_key:
        base = base.where(AgentTrigger.thread_key == thread_key)
    base = base.order_by(AgentTrigger.received_at.desc()).limit(limit).offset(offset)

    rows = (await db.execute(base)).all()
    data = [
        {
            "id": str(trigger.id),
            "source": source_name,
            "external_id": trigger.external_id,
            "thread_key": trigger.thread_key,
            "actor": trigger.actor,
            "human": trigger.human,
            "addressed": trigger.addressed,
            "payload": trigger.payload,
            "disposition": trigger.disposition or [],
            "received_at": trigger.received_at.isoformat() if trigger.received_at else None,
        }
        for trigger, source_name in rows
    ]
    return success_response(data=data)


@router.get("/triggers/{trigger_id}", summary="Trigger 详情")
async def get_trigger(
    trigger_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from uuid import UUID

    from app.core.exceptions import NotFoundException

    row = (
        await db.execute(
            select(AgentTrigger, AgentSource.name).join(
                AgentSource, AgentTrigger.source_id == AgentSource.id
            ).where(AgentTrigger.id == UUID(trigger_id))
        )
    ).first()
    if row is None:
        raise NotFoundException("Trigger 不存在")
    trigger, source_name = row
    return success_response(data={
        "id": str(trigger.id),
        "source": source_name,
        "external_id": trigger.external_id,
        "thread_key": trigger.thread_key,
        "actor": trigger.actor,
        "human": trigger.human,
        "addressed": trigger.addressed,
        "payload": trigger.payload,
        "disposition": trigger.disposition or [],
        "received_at": trigger.received_at.isoformat() if trigger.received_at else None,
    })


@router.get("/sources", summary="Source 实例列表")
async def list_sources(
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    rows = (
        await db.execute(select(AgentSource).order_by(AgentSource.name))
    ).scalars().all()
    return success_response(data=[
        {
            "id": str(row.id),
            "kind": row.kind,
            "name": row.name,
            "config": row.config,
            "enabled": row.enabled,
        }
        for row in rows
    ])


@router.get("/tasks", summary="任务列表（可按阶段过滤；阶段现算不落库）")
async def list_tasks(
    stage: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from app.platform.superagent.models import AgentTask
    from app.platform.superagent.tasks import STAGE_LABELS, derive_stage

    limit = max(1, min(limit, 200))
    base = select(AgentTask).order_by(AgentTask.created_at.desc())
    if status:
        base = base.where(AgentTask.status == status)

    # stage 是现算值无法下推 SQL：有界批量扫描凑页（batch 200，上限 10 批），
    # 防止「先分页后过滤」漏行（审查修复）
    rows: list = []
    if stage:
        for i in range(10):
            batch = (
                await db.execute(base.limit(200).offset(offset + len(rows)))
            ).scalars().all()
            rows.extend(t for t in batch if derive_stage(t.stage_facts) == stage)
            if len(rows) >= limit or len(batch) < 200:
                break
        rows = rows[:limit]
    else:
        rows = (await db.execute(base.limit(limit).offset(offset))).scalars().all()

    from app.platform.superagent.models import AgentTaskSubscription

    data = []
    for row in rows:
        derived = derive_stage(row.stage_facts)
        subs = (
            await db.execute(
                select(AgentTaskSubscription.thread_key).where(
                    AgentTaskSubscription.task_id == row.id
                )
            )
        ).scalars().all()
        data.append({
            "id": str(row.id),
            "short_name": row.short_name,
            "title": row.title,
            "executor": row.executor,
            "stage": derived,
            "stage_label": STAGE_LABELS.get(derived, derived),
            "status": row.status,
            "outcome": row.outcome,
            "mandate": row.mandate,
            "stage_facts": row.stage_facts,
            "subscriptions": list(subs),
            "origin_trigger_id": str(row.origin_trigger_id) if row.origin_trigger_id else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return success_response(data=data)


@router.get("/tasks/{task_id}", summary="任务详情（含 Mandate/Inputs/订阅）")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from uuid import UUID

    from app.core.exceptions import NotFoundException
    from app.platform.superagent.models import (
        AgentInput,
        AgentTask,
        AgentTaskSubscription,
    )
    from app.platform.superagent.tasks import STAGE_LABELS, derive_stage

    try:
        tid = UUID(task_id)
    except ValueError as exc:
        raise NotFoundException("任务不存在") from exc

    row = (
        await db.execute(select(AgentTask).where(AgentTask.id == tid))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException("任务不存在")

    inputs = (
        await db.execute(
            select(AgentInput).where(AgentInput.task_id == tid).order_by(AgentInput.created_at)
        )
    ).scalars().all()
    subs = (
        await db.execute(
            select(AgentTaskSubscription).where(AgentTaskSubscription.task_id == tid)
        )
    ).scalars().all()
    derived = derive_stage(row.stage_facts)

    return success_response(data={
        "id": str(row.id),
        "short_name": row.short_name,
        "title": row.title,
        "executor": row.executor,
        "stage": derived,
        "stage_label": STAGE_LABELS.get(derived, derived),
        "status": row.status,
        "outcome": row.outcome,
        "mandate": row.mandate,
        "stage_facts": row.stage_facts,
        "inputs": [
            {
                "id": str(i.id),
                "trigger_id": str(i.trigger_id) if i.trigger_id else None,
                "kind": i.kind,
                "payload": i.payload,
                "delivered_at": i.delivered_at.isoformat() if i.delivered_at else None,
                "read_at": i.read_at.isoformat() if i.read_at else None,
            }
            for i in inputs
        ],
        "subscriptions": [
            {"thread_key": s.thread_key, "context_only": s.context_only} for s in subs
        ],
        "origin_trigger_id": str(row.origin_trigger_id) if row.origin_trigger_id else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    })


@router.get("/state", summary="底座运行状态（健康+负载+暂停位）")
async def get_state(
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from app.core.config import get_settings
    from app.platform.superagent.models import (
        AgentEffect,
        AgentHealth,
        AgentOutboxMessage,
    )

    health_rows = (
        await db.execute(select(AgentHealth).order_by(AgentHealth.component))
    ).scalars().all()
    effects_pending = (
        await db.execute(
            select(func.count()).select_from(AgentEffect).where(AgentEffect.status == "pending")
        )
    ).scalar_one()
    effects_failed = (
        await db.execute(
            select(func.count()).select_from(AgentEffect).where(AgentEffect.status == "failed")
        )
    ).scalar_one()
    outbox_pending = (
        await db.execute(
            select(func.count()).select_from(AgentOutboxMessage)
            .where(AgentOutboxMessage.status == "pending")
        )
    ).scalar_one()
    sources_enabled = (
        await db.execute(
            select(func.count()).select_from(AgentSource).where(AgentSource.enabled.is_(True))
        )
    ).scalar_one()

    return success_response(data={
        "enabled": bool(get_settings().SUPERAGENT_ENABLED),
        "health": [
            {
                "component": row.component,
                "state": row.state,
                "detail": row.detail,
                "claimed_by": row.claimed_by,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in health_rows
        ],
        "load": {
            "effects_pending": effects_pending,
            "effects_failed": effects_failed,
            "outbox_pending": outbox_pending,
            "sources_enabled": sources_enabled,
        },
    })


@router.get("/threads", summary="Thread 列表")
async def list_threads(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    limit = max(1, min(limit, 200))
    rows = (
        await db.execute(
            select(AgentThread)
            .order_by(func.coalesce(AgentThread.last_trigger_at, AgentThread.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return success_response(data=[
        {
            "id": str(row.id),
            "thread_key": row.thread_key,
            "label": row.label,
            "url": row.url,
            "meta": row.meta,
            "last_trigger_at": row.last_trigger_at.isoformat() if row.last_trigger_at else None,
        }
        for row in rows
    ])


@router.get(
    "/threads/{thread_key}/history",
    summary="Thread 历史（按记录聚合 triggers + tasks，时间正序）",
)
async def get_thread_history(
    thread_key: str,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from app.core.exceptions import NotFoundException
    from app.platform.superagent.models import AgentTask, AgentTaskSubscription

    thread = (
        await db.execute(
            select(AgentThread).where(AgentThread.thread_key == thread_key)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFoundException("Thread 不存在")

    triggers = (
        await db.execute(
            select(AgentTrigger).where(AgentTrigger.thread_key == thread_key)
            .order_by(AgentTrigger.received_at.asc())
        )
    ).scalars().all()
    tasks = (
        await db.execute(
            select(AgentTask)
            .join(AgentTaskSubscription, AgentTaskSubscription.task_id == AgentTask.id)
            .where(AgentTaskSubscription.thread_key == thread_key)
            .order_by(AgentTask.created_at.asc())
        )
    ).scalars().all()
    return success_response(data={
        "thread": {
            "thread_key": thread.thread_key,
            "label": thread.label,
            "url": thread.url,
            "meta": thread.meta,
            "last_trigger_at": thread.last_trigger_at.isoformat()
            if thread.last_trigger_at
            else None,
        },
        "triggers": [
            {
                "id": str(t.id),
                "external_id": t.external_id,
                "actor": t.actor,
                "human": t.human,
                "payload": t.payload,
                "disposition": t.disposition or [],
                "received_at": t.received_at.isoformat() if t.received_at else None,
            }
            for t in triggers
        ],
        "tasks": [
            {
                "id": str(t.id),
                "short_name": t.short_name,
                "title": t.title,
                "executor": t.executor,
                "status": t.status,
                "outcome": t.outcome,
                "stage_facts": t.stage_facts or {},
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "ended_at": t.ended_at.isoformat() if t.ended_at else None,
            }
            for t in tasks
        ],
    })


@router.get("/decisions", summary="研判决策列表（observe 回放数据源）")
async def list_decisions(
    mode: str | None = None,
    would_accept: bool | None = None,
    unresolved: bool | None = None,
    replay: bool | None = None,
    rule_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from app.platform.superagent.models import AgentDecision, AgentTrigger

    limit = max(1, min(limit, 200))
    stmt = (
        select(AgentDecision, AgentTrigger)
        .join(AgentTrigger, AgentDecision.trigger_id == AgentTrigger.id)
        .order_by(AgentDecision.created_at.desc())
    )
    if mode:
        stmt = stmt.where(AgentDecision.mode == mode)
    if would_accept is not None:
        stmt = stmt.where(AgentDecision.would_accept.is_(would_accept))
    if replay is not None:
        stmt = stmt.where(AgentDecision.replay.is_(replay))
    if rule_id:
        stmt = stmt.where(AgentDecision.rule_id == rule_id)
    if unresolved:
        stmt = stmt.where(AgentDecision.resolution.is_(None))
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()

    return success_response(data=[
        {
            "id": str(d.id),
            "trigger_id": str(d.trigger_id),
            "trigger_external_id": t.external_id,
            "trigger_payload": t.payload,
            "rule_id": d.rule_id,
            "outcome": d.outcome,
            "would_accept": d.would_accept,
            "reason": d.reason,
            "policy_version": d.policy_version,
            "mode": d.mode,
            "replay": d.replay,
            "resolution": d.resolution,
            "resolved_by": d.resolved_by,
            "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d, t in rows
    ])


@router.post("/decisions/{decision_id}/promote", summary="observe 决策转正（人工；require_admin）")
async def promote_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    admin: RequireAdmin,
) -> JSONResponse:
    from uuid import UUID

    from app.core.exceptions import AppException, NotFoundException
    from app.platform.superagent.models import AgentDecision
    from app.platform.superagent.policy import resolve_decision

    try:
        did = UUID(decision_id)
    except ValueError as exc:
        raise NotFoundException("决策不存在") from exc

    decision = (
        await db.execute(select(AgentDecision).where(AgentDecision.id == did))
    ).scalar_one_or_none()
    if decision is None:
        raise NotFoundException("决策不存在")
    if decision.resolution:
        raise AppException(status_code=409, message=f"决策已处置（{decision.resolution}）")
    if not decision.would_accept:
        raise AppException(status_code=400, message="仅 would_accept 决策可转正")

    task = await resolve_decision(
        db, decision, resolution="promoted",
        resolved_by=str(getattr(admin, "id", "") or ""),
    )
    await db.commit()
    return success_response(data={
        "decision_id": str(decision.id),
        "resolution": decision.resolution,
        "task_id": str(task.id) if task else None,
    })


@router.post("/decisions/{decision_id}/dismiss", summary="observe 决策忽略（人工；require_admin）")
async def dismiss_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db),
    *,
    admin: RequireAdmin,
) -> JSONResponse:
    from uuid import UUID

    from app.core.exceptions import AppException, NotFoundException
    from app.platform.superagent.models import AgentDecision
    from app.platform.superagent.policy import resolve_decision

    try:
        did = UUID(decision_id)
    except ValueError as exc:
        raise NotFoundException("决策不存在") from exc

    decision = (
        await db.execute(select(AgentDecision).where(AgentDecision.id == did))
    ).scalar_one_or_none()
    if decision is None:
        raise NotFoundException("决策不存在")
    if decision.resolution:
        raise AppException(status_code=409, message=f"决策已处置（{decision.resolution}）")

    await resolve_decision(
        db, decision, resolution="dismissed",
        resolved_by=str(getattr(admin, "id", "") or ""),
    )
    await db.commit()
    return success_response(data={"decision_id": str(decision.id), "resolution": "dismissed"})


@router.get("/needs-human", summary="「需要人」快照（速递格同源数据）")
async def get_needs_human(
    db: AsyncSession = Depends(get_db),
    *,
    _user: RequireUser,
) -> JSONResponse:
    from app.platform.superagent.watchdog import build_needs_human_snapshot

    snapshot = await build_needs_human_snapshot(db)
    return success_response(data=snapshot)


@router.post("/sources/{source_id}/toggle", summary="Source 实例启停（人工；require_admin）")
async def toggle_source(
    source_id: str,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
    *,
    _admin: RequireAdmin,
) -> JSONResponse:
    """启停一个 Source 实例（含 observe 源；observe→auto 切换走 Policy 改版，
    本端点只管实例开关——系统无任何自动切换路径）。"""
    from uuid import UUID

    from app.core.exceptions import NotFoundException
    from app.platform.superagent.models import AgentSource

    try:
        sid = UUID(source_id)
    except ValueError as exc:
        raise NotFoundException("Source 不存在") from exc

    row = (
        await db.execute(select(AgentSource).where(AgentSource.id == sid))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundException("Source 不存在")

    row.enabled = bool(enabled)
    await db.commit()
    return success_response(data={"id": str(row.id), "name": row.name, "enabled": row.enabled})
