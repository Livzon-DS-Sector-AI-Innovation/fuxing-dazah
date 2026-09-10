"""业务 Agent 会话持久层。

管理三份持久化数据：
- ``AgentSession`` — 会话元信息 + 序列化的消息历史（JSONB）
- ``AgentMessage`` — 按轮次的对话记录（审计索引）
- ``AgentPendingAction`` — 挂起的写操作

调用方：executor.py 不直接访问 DB——入口适配器（Web router / 飞书 handler）
调用本模块的方法持久化执行结果。executor.py 本身保持无状态。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.safety.business_agent.models import (
    AgentMessage,
    AgentPendingAction,
    AgentSession,
    AgentUserRole,
)
from app.modules.safety.business_agent.schemas import (
    PendingActionData,
    PendingActionStatus,
)

if TYPE_CHECKING:
    import uuid

    from pydantic_ai.messages import ModelMessage
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.safety.business_agent.core.events import AgentSessionEvent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# session 事件流（S3，转发到 core/events.py，保持调用方 import 路径稳定）
# ═══════════════════════════════════════════════════════════════


async def append_event(db: AsyncSession, *, session_id: uuid.UUID, event_type: str, payload: dict):
    """向会话追加一条事件（转发到 core/events.append_event）。"""
    from app.modules.safety.business_agent.core import events
    return await events.append_event(
        db, session_id=session_id, event_type=event_type, payload=payload,
    )


async def get_events(db: AsyncSession, session_id: uuid.UUID) -> list[AgentSessionEvent]:
    """按 seq 升序取会话全部未删除事件（转发到 core/events.get_events）。"""
    from app.modules.safety.business_agent.core import events
    return await events.get_events(db, session_id)


async def derive_messages(db: AsyncSession, session_id: uuid.UUID) -> list[ModelMessage]:
    """从事件流派生 LLM 上下文消息列表（转发到 core/events.derive_messages）。"""
    from app.modules.safety.business_agent.core import events
    evs = await events.get_events(db, session_id)
    return events.derive_messages(evs)


# ═══════════════════════════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════════════════════════


async def get_or_create_session(
    db: AsyncSession,
    *,
    channel: str = "web",
    chat_id: str | None = None,
    user_id: str | None = None,
    role: str | None = None,
) -> AgentSession:
    """按 channel + chat_id 获取已有会话，不存在则创建。"""
    stmt = select(AgentSession).where(
        AgentSession.channel == channel,
        AgentSession.chat_id == chat_id,
        AgentSession.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is not None:
        session.last_active_at = datetime.now(UTC)
        await db.flush()
        return session

    session = AgentSession(
        channel=channel,
        chat_id=chat_id,
        user_id=user_id,
        role=role,
        last_active_at=datetime.now(UTC),
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: str) -> AgentSession | None:
    """按 ID 查询会话。"""
    stmt = select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_session_history(
    db: AsyncSession,
    session: AgentSession,
    *,
    messages: list[dict],
    title: str | None = None,
) -> None:
    """更新会话的消息历史；首轮时可选设置标题。"""
    session.message_history = messages
    session.message_count = session.message_count + 1
    session.last_active_at = datetime.now(UTC)
    if title and not session.title:
        session.title = title[:256]
    await db.flush()


async def reset_all_sessions(db: AsyncSession) -> int:
    """服务器重启时调用：软删除所有活跃会话，重置全部对话上下文。

    下次用户发消息时 ``get_or_create_session`` 会创建全新会话（空 message_history），
    防止跨重启的旧上下文污染模型推理。

    同时将处于 pending 状态的挂起操作标记为 expired（重启后模型进程已不存在，
    无法继续执行之前的挂起写操作）。

    Returns:
        软删除的会话数量。
    """
    from sqlalchemy import update

    # ① 软删除所有活跃会话
    stmt = (
        update(AgentSession)
        .where(AgentSession.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    result = await db.execute(stmt)
    session_count = result.rowcount

    # ② 将 pending 状态的挂起操作标记为 expired
    stmt2 = (
        update(AgentPendingAction)
        .where(
            AgentPendingAction.is_deleted == False,  # noqa: E712
            AgentPendingAction.status == PendingActionStatus.PENDING,
        )
        .values(status=PendingActionStatus.EXPIRED)
    )
    await db.execute(stmt2)

    if session_count:
        logger.info(
            "Agent session reset: soft-deleted %d active sessions, expired pending actions",
            session_count,
        )
    return session_count


# ═══════════════════════════════════════════════════════════════
# 消息记录（审计用）
# ═══════════════════════════════════════════════════════════════


async def save_message(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_message: str,
    agent_answer: str,
    pending_action_id: uuid.UUID | None = None,
) -> AgentMessage:
    """保存一轮对话记录（append-only 审计日志）。"""
    record = AgentMessage(
        session_id=session_id,
        user_message=user_message,
        agent_answer=agent_answer,
        pending_action_id=pending_action_id,
    )
    db.add(record)
    await db.flush()
    return record


# ═══════════════════════════════════════════════════════════════
# 挂起动作
# ═══════════════════════════════════════════════════════════════


async def create_pending_action(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    pending: PendingActionData,
    message_history_snapshot: list[dict],
) -> AgentPendingAction:
    """创建一条挂起的写操作记录（status=pending）。"""
    record = AgentPendingAction(
        session_id=session_id,
        tool_name=pending.tool_name,
        arguments=pending.arguments,
        summary=pending.summary,
        status=PendingActionStatus.PENDING,
        message_history_snapshot=message_history_snapshot,
    )
    db.add(record)
    await db.flush()
    return record


async def get_pending_action(
    db: AsyncSession, action_id: str,
) -> AgentPendingAction | None:
    """按 ID 查询挂起动作。"""
    stmt = select(AgentPendingAction).where(
        AgentPendingAction.id == action_id,
        AgentPendingAction.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def set_card_message_id(
    db: AsyncSession, action_id: str, card_message_id: str,
) -> None:
    """记录确认卡片的消息 ID（用于后续更新卡片状态）。"""
    stmt = select(AgentPendingAction).where(
        AgentPendingAction.id == action_id,
        AgentPendingAction.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()
    if action:
        action.card_message_id = card_message_id
        await db.flush()


async def resolve_pending_action(
    db: AsyncSession,
    action: AgentPendingAction,
    *,
    approved: bool,
    approved_by: str | None = None,
    result_data: dict | None = None,
    error_message: str | None = None,
) -> None:
    """更新挂起动作的状态（确认/拒绝/执行成功/失败）。"""
    if approved:
        action.status = PendingActionStatus.EXECUTED if result_data else PendingActionStatus.CONFIRMED
        action.result = result_data
    else:
        action.status = PendingActionStatus.REJECTED
    if error_message:
        action.status = PendingActionStatus.FAILED
        action.result = {"error": error_message}
    action.approved_by = approved_by
    action.executed_at = datetime.now(UTC)
    await db.flush()


# ═══════════════════════════════════════════════════════════════
# 角色
# ═══════════════════════════════════════════════════════════════


async def get_user_role(db: AsyncSession, feishu_user_id: str) -> str | None:
    """查询用户的角色绑定；未绑定返回 None（deny-by-default）。"""
    stmt = select(AgentUserRole).where(
        AgentUserRole.feishu_user_id == feishu_user_id,
        AgentUserRole.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row.role if row else None
