"""业务 Agent 持久化模型。

四张表（均在 ``safety`` schema）：

- ``agent_sessions``：会话（一个飞书 chat_id 或 Web session）
- ``agent_messages``：序列化的对话历史（每轮一条记录，JSONB 存储完整的 ModelMessages 列表）
- ``agent_pending_actions``：挂起的写操作（等待用户确认/取消）
- ``agent_user_roles``：用户角色绑定（feishu_user_id → role，deny-by-default）

设计原则：
- 软删除（``is_deleted``），不物理删除历史和操作记录
- 外键通过字段命名约定关联，不创建数据库级 FK 约束（符合项目规范）
- 消息体用 JSONB 存储；角色表独立维护
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class AgentSession(BaseModel):
    """Agent 会话。

    一个会话 = 一个飞书群聊 / 私聊，或一个 Web 前端会话。message_history
    字段存储序列化的 ``ModelMessagesTypeAdapter.dump_python()`` 产物。
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index("ix_agent_sessions_channel_chat_id", "channel", "chat_id"),
        {"schema": "safety"},
    )

    channel: Mapped[str] = mapped_column(
        String(32), default="web", comment="入口渠道：feishu / web"
    )
    chat_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书 chat_id；web 入口的 session_id"
    )
    title: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="会话标题（首条消息摘要）"
    )
    message_history: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="ModelMessagesTypeAdapter.dump_python() 序列化结果"
    )
    message_count: Mapped[int] = mapped_column(
        default=0, server_default="0", comment="消息轮数"
    )
    user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="关联 identity.users.feishu_user_id"
    )
    role: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="会话建立时的角色（快照，不随角色变更而变）"
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        comment="最后活跃时间",
    )


class AgentMessage(BaseModel):
    """单轮对话记录（审计用）。

    与 agent_sessions 的 message_history（JSONB 整体存储）互补：本表按轮次索引，
    方便审计和搜索。message_history 仍然是 Agent 运行的主数据。
    """

    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_session_id", "session_id"), {"schema": "safety"})

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="关联 agent_sessions.id"
    )
    user_message: Mapped[str] = mapped_column(Text, comment="用户输入原文")
    agent_answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Agent 回复原文"
    )
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 agent_pending_actions.id（若本轮产生了挂起操作）"
    )


class AgentPendingAction(BaseModel):
    """挂起的写操作（等待用户确认）。

    写入类工具调用被 ``requires_approval`` 拦截后，作为记录暂存于此：
    - status=pending → 等待用户确认
    - status=confirmed → 用户已确认，待 executor.resume() 执行
    - status=executed → 已执行成功
    - status=rejected → 用户取消
    - status=failed / expired → 执行失败 / 超时
    """

    __tablename__ = "agent_pending_actions"
    __table_args__ = (
        Index("ix_agent_pending_actions_session_id", "session_id"),
        {"schema": "safety"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="关联 agent_sessions.id"
    )
    tool_name: Mapped[str] = mapped_column(
        String(128), comment="将要执行的写工具名"
    )
    arguments: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="工具调用参数"
    )
    summary: Mapped[str] = mapped_column(
        Text, comment="面向用户的执行方案描述"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending",
        comment="pending / confirmed / executed / rejected / failed / expired",
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="执行完成时间"
    )
    result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="执行结果（成功时记录返回值，失败时记录错误）"
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="确认人 feishu_user_id"
    )
    message_history_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="挂起时的消息历史快照（用于 resume 回溯 DeferredToolRequests）",
    )
    card_message_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书确认卡片的 message_id（用于点击按钮后更新卡片状态）"
    )


class AgentUserRole(BaseModel):
    """用户角色绑定。

    将飞书 user_id 映射到固定角色（safety_admin / dept_leader / inspector / viewer）。
    角色对应权限见 ``permissions.py`` 的 ``ROLE_TOOL_POLICY``。
    """

    __tablename__ = "agent_user_roles"
    __table_args__ = (
        Index("ix_agent_user_roles_feishu_user_id", "feishu_user_id", unique=True),
        {"schema": "safety"},
    )

    feishu_user_id: Mapped[str] = mapped_column(
        String(128), unique=True, comment="identity.users.feishu_user_id"
    )
    role: Mapped[str] = mapped_column(
        String(64), comment="角色：safety_admin / dept_leader / inspector / viewer"
    )
    display_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="备注/显示名"
    )
