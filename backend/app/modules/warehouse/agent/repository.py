"""Warehouse Agent 数据读写（sessions / audit / drafts）。只负责读写，不含业务规则。

gateway（会话定位、审计落库）与 confirm（确认草稿状态机）共用本模块。
软删除语义（BaseModel.is_deleted）：全部查询显式过滤 is_deleted == False。

SQLAlchemy async 铁律（CLAUDE.md）：INSERT → flush 后 RETURNING 已回填 id，
直接返回无需 re-fetch；UPDATE → flush 后不 re-fetch（调用方仅在事务存活期间
访问内存已加载属性，无 MissingGreenlet 风险）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseAgentAudit,
    WarehouseAgentDraft,
    WarehouseAgentMemory,
    WarehouseAgentPlan,
    WarehouseAgentSession,
)

# ── 会话（warehouse_agent_sessions）──


async def get_session(
    db: AsyncSession, *, chat_id: str, user_open_id: str
) -> WarehouseAgentSession | None:
    stmt = select(WarehouseAgentSession).where(
        WarehouseAgentSession.chat_id == chat_id,
        WarehouseAgentSession.user_open_id == user_open_id,
        WarehouseAgentSession.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession, *, chat_id: str, user_open_id: str
) -> WarehouseAgentSession:
    """按 (chat_id, open_id) 定位会话，不存在则创建。

    并发兜底：部分唯一索引 uq_warehouse_agent_sessions_key 冲突时回滚重查。
    注意 rollback 会回滚本事务之前的未提交写入，因此调用方应把本函数放在
    事务的首个写操作位置（gateway 文本路径即如此）。
    """
    existing = await get_session(db, chat_id=chat_id, user_open_id=user_open_id)
    if existing is not None:
        return existing
    session = WarehouseAgentSession(chat_id=chat_id, user_open_id=user_open_id, history={})
    db.add(session)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await get_session(db, chat_id=chat_id, user_open_id=user_open_id)
        if existing is None:
            raise
        return existing
    return session


async def update_session_history(
    db: AsyncSession, session_id: uuid.UUID, history: dict[str, Any]
) -> None:
    """覆盖会话历史 JSONB（调用方负责裁剪与结构）。"""
    session = await db.get(WarehouseAgentSession, session_id)
    if session is None or session.is_deleted:
        return
    session.history = history
    await db.flush()


# ── 审计（warehouse_agent_audit）──


async def insert_agent_audit(
    db: AsyncSession,
    *,
    tool_name: str,
    args_summary: dict[str, Any] | None = None,
    result_status: str,
    error_code: str | None = None,
    duration_ms: int = 0,
    session_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
) -> WarehouseAgentAudit:
    """写入一条工具调用审计记录（INSERT → flush 返回即可）。"""
    audit = WarehouseAgentAudit(
        tool_name=tool_name,
        args_summary=args_summary or {},
        result_status=result_status,
        error_code=error_code,
        duration_ms=duration_ms,
        session_id=session_id,
        draft_id=draft_id,
    )
    db.add(audit)
    await db.flush()
    return audit


# ── 确认草稿（warehouse_agent_drafts，confirm 状态机载体）──


async def create_agent_draft(
    db: AsyncSession,
    *,
    draft_no: str,
    scene: str,
    status: str,
    created_by_open_id: str | None = None,
    aligned: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> WarehouseAgentDraft:
    draft = WarehouseAgentDraft(
        draft_no=draft_no,
        scene=scene,
        status=status,
        created_by_open_id=created_by_open_id,
        aligned=aligned or {},
        expires_at=expires_at,
    )
    db.add(draft)
    await db.flush()
    return draft


async def get_agent_draft(
    db: AsyncSession, draft_id: uuid.UUID
) -> WarehouseAgentDraft | None:
    draft = await db.get(WarehouseAgentDraft, draft_id)
    if draft is None or draft.is_deleted:
        return None
    return draft


async def set_agent_draft_status(
    db: AsyncSession, draft: WarehouseAgentDraft, status: str
) -> None:
    """状态机流转（仅赋值 + flush；updated_at 由 onupdate 落库，内存不回填亦不访问）。"""
    draft.status = status
    await db.flush()


# ── 任务计划（warehouse_agent_plans，ticket 05）──


async def insert_plan(
    db: AsyncSession,
    *,
    plan_no: str,
    title: str,
    steps: list[dict[str, Any]],
    session_id: uuid.UUID | None = None,
    created_by_open_id: str | None = None,
) -> WarehouseAgentPlan:
    """写入一条任务计划（status 固定 active 起步；steps 为初始化后的步骤列表）。"""
    plan = WarehouseAgentPlan(
        plan_no=plan_no,
        title=title,
        steps=steps,
        status="active",
        session_id=session_id,
        created_by_open_id=created_by_open_id,
    )
    db.add(plan)
    await db.flush()
    return plan


async def list_actionable_drafts(
    db: AsyncSession, owner_open_id: str, limit: int = 5
) -> list[WarehouseAgentDraft]:
    """某用户当前待处理事项：pending_confirm 确认草稿 + scheduled 未触发提醒。

    供 Runner 注入「当前待处理」上下文（spec 决策 5：pending 草稿摘要），
    让 Agent 感知「刚才那个发送」「明早的提醒」并自然回应追问。
    """
    from datetime import datetime as _dt
    from datetime import UTC as _UTC
    from sqlalchemy import select as _select

    stmt = (
        _select(WarehouseAgentDraft)
        .where(
            WarehouseAgentDraft.created_by_open_id == owner_open_id,
            WarehouseAgentDraft.is_deleted.is_(False),
            WarehouseAgentDraft.status.in_(["pending_confirm", "scheduled"]),
        )
        .order_by(WarehouseAgentDraft.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    now = _dt.now(_UTC)
    return [
        r
        for r in rows
        if r.expires_at is None or r.expires_at > now
    ]


async def get_plan_by_no(
    db: AsyncSession, *, plan_no: str
) -> WarehouseAgentPlan | None:
    stmt = select(WarehouseAgentPlan).where(
        WarehouseAgentPlan.plan_no == plan_no,
        WarehouseAgentPlan.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_active_plans(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None = None,
    created_by_open_id: str | None = None,
    limit: int = 3,
) -> list[WarehouseAgentPlan]:
    """进行中的计划（status=active），按创建时间倒序。

    session_id 优先定位本会话的计划，否则按发起人 open_id 跨会话定位
    （中断恢复入口，ticket 05）。
    """
    stmt = select(WarehouseAgentPlan).where(
        WarehouseAgentPlan.status == "active",
        WarehouseAgentPlan.is_deleted == False,  # noqa: E712
    )
    if session_id is not None:
        stmt = stmt.where(WarehouseAgentPlan.session_id == session_id)
    elif created_by_open_id:
        stmt = stmt.where(WarehouseAgentPlan.created_by_open_id == created_by_open_id)
    stmt = stmt.order_by(WarehouseAgentPlan.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def get_latest_plan_no_on_prefix(
    db: AsyncSession, *, prefix: str
) -> str | None:
    """同前缀（WP+日期）的最大 plan_no（plan_no 序号生成用，字典序=序号序）。"""
    stmt = (
        select(WarehouseAgentPlan.plan_no)
        .where(
            WarehouseAgentPlan.plan_no.like(f"{prefix}%"),
            WarehouseAgentPlan.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseAgentPlan.plan_no.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ── 长期记忆（warehouse_agent_memories，ticket 06）──


async def insert_memory(
    db: AsyncSession,
    *,
    scope: str,
    owner_open_id: str | None,
    memory_type: str,
    content: str,
) -> WarehouseAgentMemory:
    """写入一条长期记忆（scope=user 时 owner 必填、global 时为空，由调用方保证）。"""
    memory = WarehouseAgentMemory(
        scope=scope,
        owner_open_id=owner_open_id,
        memory_type=memory_type,
        content=content,
    )
    db.add(memory)
    await db.flush()
    return memory


async def list_recallable_memories(
    db: AsyncSession,
    *,
    owner_open_id: str,
    keyword: str | None = None,
    limit: int = 20,
) -> list[WarehouseAgentMemory]:
    """可检索记忆：该用户的（scope=user 且 owner 匹配）+ 全局的（scope=global），
    按 updated_at 倒序。

    keyword 非空时对 content 做 ILIKE 模糊匹配（%/_ 视为通配符，
    业务关键词场景不做转义）。
    """
    stmt = select(WarehouseAgentMemory).where(
        or_(
            and_(
                WarehouseAgentMemory.scope == "user",
                WarehouseAgentMemory.owner_open_id == owner_open_id,
            ),
            WarehouseAgentMemory.scope == "global",
        ),
        WarehouseAgentMemory.is_deleted == False,  # noqa: E712
    )
    if keyword:
        stmt = stmt.where(WarehouseAgentMemory.content.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(WarehouseAgentMemory.updated_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def list_user_preferences(
    db: AsyncSession, *, owner_open_id: str, limit: int = 3
) -> list[WarehouseAgentMemory]:
    """该用户的偏好（scope=user + preference），updated_at 倒序取前 limit 条。"""
    stmt = (
        select(WarehouseAgentMemory)
        .where(
            WarehouseAgentMemory.scope == "user",
            WarehouseAgentMemory.owner_open_id == owner_open_id,
            WarehouseAgentMemory.memory_type == "preference",
            WarehouseAgentMemory.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseAgentMemory.updated_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_global_knowledge(
    db: AsyncSession, *, limit: int = 5
) -> list[WarehouseAgentMemory]:
    """全局惯例与术语别名（scope=global + convention/alias），updated_at 倒序取前 limit 条。"""
    stmt = (
        select(WarehouseAgentMemory)
        .where(
            WarehouseAgentMemory.scope == "global",
            WarehouseAgentMemory.memory_type.in_(("convention", "alias")),
            WarehouseAgentMemory.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseAgentMemory.updated_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def bump_memory_hit_counts(
    db: AsyncSession, memories: list[WarehouseAgentMemory]
) -> None:
    """被返回/注入的记忆 hit_count += 1（淘汰依据）。

    注意：UPDATE 会触发 updated_at 的 onupdate 刷新，被命中过的记忆在
    后续注入排序中按「最近命中时间」上浮（recency+frequency 混合效应，
    取数先于 bump，单次调用的结果集不受影响）。
    """
    for memory in memories:
        memory.hit_count = (memory.hit_count or 0) + 1
    await db.flush()
