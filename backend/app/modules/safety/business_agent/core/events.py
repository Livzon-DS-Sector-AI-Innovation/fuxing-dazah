"""session 事件流（S3）。

事件源表 ``safety.agent_session_events``（append-only）替代 ``agent_sessions.message_history``
整包覆写。LLM 消息历史由 ``derive_messages(events)`` 派生，本表是唯一事实源。

职责：
- ``AgentSessionEvent`` ORM：事件模型（继承 BaseModel，事件列追加在 §2.1 DDL）。
- ``append_event``：per session 单调递增 seq（``max(seq)+1``）事务内写入。
- ``derive_messages``：按 seq 顺序重建 Pydantic AI ``ModelMessage`` 列表，与旧 ``message_history`` 等价
  （自动化对齐测试持续跑，双写期间保证一致）。
- ``get_events``：按 seq 升序取会话全部未删除事件。

设计遵循 CLAUDE.md：软删除（不物理删）、不用 FK 约束（session_id 命名约定关联）、
SQLAlchemy 2.0 typed ORM、async（INSERT 后 ``flush`` 返回即可，无需 re-fetch）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from sqlalchemy import Index, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── event_type 枚举常量（代码常量，不建 PG enum，便于加类型不加迁移） ──
class EventType:
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    MEMORY_WRITE = "memory_write"
    TURN_END = "turn_end"

    ALL = (
        USER_MESSAGE,
        ASSISTANT_MESSAGE,
        TOOL_CALL,
        TOOL_RESULT,
        APPROVAL_REQUESTED,
        APPROVAL_RESOLVED,
        MEMORY_WRITE,
        TURN_END,
    )


class AgentSessionEvent(BaseModel):
    """Agent 会话事件流（append-only，事件源）。

    LLM 消息历史由 ``derive_messages(events)`` 派生；本表是唯一事实源。
    误写事件走软删 + ``append`` 新 seq（禁止复用 seq，避免「删→加→删→加」循环 bug）。
    """

    __tablename__ = "agent_session_events"
    __table_args__ = (
        Index("ix_agent_session_events_session_seq", "session_id", "seq", unique=True),
        Index("ix_agent_session_events_session_created", "session_id", "created_at"),
        Index("ix_agent_session_events_type", "event_type"),
        {"schema": "safety"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="关联 agent_sessions.id（命名约定，无 FK 约束）",
    )
    seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="per session 单调递增序列号（从 1 起，不复用）",
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="user_message | assistant_message | tool_call | tool_result | "
        "approval_requested | approval_resolved | memory_write | turn_end",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="事件载荷（见 backend-design §2.1.2 payload schema）",
    )


# ═══════════════════════════════════════════════════════════════
# 事件写入
# ═══════════════════════════════════════════════════════════════


async def append_event(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> AgentSessionEvent:
    """向会话追加一条事件，返回带 ``seq`` 的持久化事件。

    同事务内读当前最大 ``seq`` + 1（per session 单调递增），``flush`` 后返回
    （INSERT RETURNING 回填 id/created_at，无需 re-fetch，符合 async 铁律）。

    并发保护：run_turn/resume 单会话串行执行（入口层已按 chat_id 串行化），per-session
    并发低；(session_id, seq) 唯一索引兜底防重。

    TODO(并发兜底，如需强一致)：append 前对 session_id 取 ``pg_advisory_xact_lock``——
    ``SELECT pg_advisory_xact_lock(hashtext(session_id::text))``，事务结束自动释放。当前
    测试环境（SQLite/临时事务）不便验证，留作后续接入真实并发压测时启用。
    """
    stmt = (
        select(func.coalesce(func.max(AgentSessionEvent.seq), 0) + 1)
        .where(
            AgentSessionEvent.session_id == session_id,
            AgentSessionEvent.is_deleted == False,  # noqa: E712
        )
    )
    next_seq = (await db.execute(stmt)).scalar_one()
    event = AgentSessionEvent(
        session_id=session_id,
        seq=int(next_seq),
        event_type=event_type,
        payload=payload or {},
    )
    db.add(event)
    await db.flush()
    return event


# ═══════════════════════════════════════════════════════════════
# 事件查询 + 消息派生
# ═══════════════════════════════════════════════════════════════


async def get_events(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> list[AgentSessionEvent]:
    """按 ``seq`` 升序返回会话全部未删除事件。"""
    stmt = (
        select(AgentSessionEvent)
        .where(
            AgentSessionEvent.session_id == session_id,
            AgentSessionEvent.is_deleted == False,  # noqa: E712
        )
        .order_by(AgentSessionEvent.seq.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


def derive_messages(events: list[AgentSessionEvent]) -> list[ModelMessage]:
    """从事件流派生 LLM 上下文消息列表，与旧 ``message_history`` 等价（US2）。

    算法：按 ``seq`` 顺序归并事件 → 构造 ``ModelRequest``/``ModelResponse``。
    - ``user_message`` → ``ModelRequest(parts=[UserPromptPart(content)])``
    - ``assistant_message`` → ``ModelResponse(parts=[TextPart(content)])``
    - ``tool_call`` → ``ModelResponse(parts=[ToolCallPart(...)])``（累积同轮多个 call 合并进一个 ModelResponse）
    - ``tool_result`` → ``ModelRequest(parts=[ToolReturnPart(...)])``（同 call_id 对齐）
    - ``approval_requested/resolved`` → 不产生消息（挂起语义由 resume 时 DeferredToolResults 承载）
    - ``memory_write/turn_end`` → 跳过（非 LLM 消息）
    """
    messages: list[ModelMessage] = []
    pending_tool_calls: list[ToolCallPart] = []
    pending_tool_returns: list[ToolReturnPart] = []

    for ev in events:
        p = ev.payload or {}
        match ev.event_type:
            case EventType.USER_MESSAGE:
                _flush_parts(messages, pending_tool_calls, pending_tool_returns)
                messages.append(
                    ModelRequest(parts=[UserPromptPart(content=str(p.get("content", "")))])
                )
            case EventType.ASSISTANT_MESSAGE:
                _flush_parts(messages, pending_tool_calls, pending_tool_returns)
                messages.append(
                    ModelResponse(parts=[TextPart(content=str(p.get("content", "")))])
                )
            case EventType.TOOL_CALL:
                pending_tool_calls.append(
                    ToolCallPart(
                        tool_name=p.get("tool_name", ""),
                        args=p.get("args"),
                        tool_call_id=p.get("tool_call_id", ""),
                    )
                )
            case EventType.TOOL_RESULT:
                content = p.get("data") or p.get("error") or ""
                pending_tool_returns.append(
                    ToolReturnPart(
                        tool_name=p.get("tool_name", ""),
                        tool_call_id=p.get("tool_call_id", ""),
                        content=content,
                        outcome=(
                            "denied"
                            if p.get("ok") is False and p.get("denied")
                            else ("failed" if p.get("ok") is False else "success")
                        ),
                    )
                )
            case _:
                # approval_requested / approval_resolved / memory_write / turn_end 不参与消息派生
                continue

    _flush_parts(messages, pending_tool_calls, pending_tool_returns)

    # 用 ModelMessagesTypeAdapter 校验派生结果可序列化（等价旧 message_history 序列化产物）
    ModelMessagesTypeAdapter.validate_python(messages)
    return messages


def _flush_parts(
    messages: list[ModelMessage],
    pending_tool_calls: list[ToolCallPart],
    pending_tool_returns: list[ToolReturnPart],
) -> None:
    """把累积的 tool 调用/返回 parts 包成对应 ModelMessage 追加。

    与旧 ``message_history`` 的预期顺序一致（事件 append 序列：user → tool_call → tool_result →
    assistant），因此 tool_call 先于 tool_result 入列。"""
    if pending_tool_calls:
        messages.append(ModelResponse(parts=list(pending_tool_calls)))
        pending_tool_calls.clear()
    if pending_tool_returns:
        messages.append(ModelRequest(parts=list(pending_tool_returns)))
        pending_tool_returns.clear()
