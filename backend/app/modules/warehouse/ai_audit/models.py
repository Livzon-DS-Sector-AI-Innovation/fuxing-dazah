"""AI 调用审计表模型（warehouse.ai_call_audits）。

每次 ``chat_with_tools`` 一行（与 warehouse_agent_audit 工具调用审计经
session_id + trace_id 关联：一个回答「Agent 做了什么操作」，一个回答
「模型收到什么、返回了什么」）。写入走独立 DB 会话（业务事务回滚不抹掉
「调用已发生」），写入失败只记 ERROR 不阻塞业务。
"""

import uuid
from typing import Any

from sqlalchemy import Index, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class AiCallAudit(BaseModel):
    """LLM 调用审计（append-only，业务不做删除）。"""

    __tablename__ = "ai_call_audits"
    __table_args__ = (
        Index("ix_warehouse_ai_call_audits_scenario_created", "scenario", "created_at"),
        Index("ix_warehouse_ai_call_audits_trace", "trace_id"),
        Index("ix_warehouse_ai_call_audits_session", "session_id"),
        Index("ix_warehouse_ai_call_audits_created", "created_at"),
        {"schema": "warehouse"},
    )

    trace_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="一次 Runner.run / 识别管线的追踪 ID（UUID）"
    )
    scenario: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="场景（agent_chat / receipt_recognition）"
    )
    resource: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="场景内细分（chat / rotate_detect / receipt_parse）",
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False, comment="模型名")
    prompt_version: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="system 消息 sha256 前 12 位"
    )
    input_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="请求消息（64K 字符截断 + truncated 标志）"
    )
    output_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="响应 content + tool_calls（64K 截断）"
    )
    tool_names: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="本轮模型请求的 tool_calls 名称"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="success / failed"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误摘要")
    input_tokens: Mapped[int | None] = mapped_column(
        Numeric(12), nullable=True, comment="输入 token"
    )
    output_tokens: Mapped[int | None] = mapped_column(
        Numeric(12), nullable=True, comment="输出 token（含 reasoning）"
    )
    cache_hit_tokens: Mapped[int | None] = mapped_column(
        Numeric(12), nullable=True, comment="prompt 缓存命中 token"
    )
    cache_miss_tokens: Mapped[int | None] = mapped_column(
        Numeric(12), nullable=True, comment="prompt 缓存未命中 token"
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Numeric(12), nullable=True, comment="耗时毫秒"
    )
    degradation_level: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="降级标记（backup_model）；正常为空"
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="关联会话"
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="关联草稿（识别入库场景）"
    )
    chat_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="发起会话（群/私聊 chat_id）"
    )
    user_open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="发起人飞书 open_id"
    )
    channel: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="触发渠道（feishu）"
    )
