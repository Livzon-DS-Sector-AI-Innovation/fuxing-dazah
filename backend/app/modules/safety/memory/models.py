"""Agent 长期记忆持久化模型。

表（均在 ``safety`` schema）：
  - ``agent_memories``：跨会话用户记忆，支持 fact/preference/episode/workflow 四种类型。

设计原则：
  - 软删除（``is_deleted``），不物理删除记忆
  - user_id 隔离（每条记忆归属一个用户）
  - embedding 存储为 JSON TEXT（与 RegulationChunk 一致，暂不用 pgvector）
  - 可追溯来源会话和消息
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class AgentMemory(BaseModel):
    """跨会话用户记忆。

    每次 Agent 对话后，MemoryExtractor 从对话中提取结构化事实并存储于此。
    每次新对话开始前，MemoryRetriever 检索相关记忆并注入 Agent context。
    """

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_user_type", "user_id", "memory_type"),
        Index("ix_agent_memories_user_importance", "user_id", "importance"),
        Index("ix_agent_memories_superseded_by", "superseded_by"),
        {"schema": "safety"},
    )

    user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="identity.users.feishu_user_id"
    )
    memory_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="记忆类型：fact / preference / episode / workflow",
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="人类可读的记忆内容"
    )
    embedding: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="JSON-stringified 2048-dim 向量（供语义检索）"
    )
    importance: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5", comment="重要性评分 (0-1)"
    )
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0, server_default="1.0", comment="置信度 (0-1)"
    )
    access_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="被检索次数"
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后检索时间"
    )
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="来源会话（agent_sessions.id）"
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None,
        comment="被哪条记忆取代（冲突合并：相似度>0.85 时旧记忆置 superseded_by=新记忆 id）",
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="来源消息（agent_messages.id）"
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata_", JSONB, default=dict, comment="扩展元数据"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="过期时间（NULL=永不过期）"
    )
