"""法规收录留痕 ORM（契约①接收侧，平台 DB 留痕类）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class RegulationIngestRun(BaseModel):
    """法规收录 run 级留痕（一次契约①批次推送一行）。

    source_run_id = ragplus 侧爬取 run_id，幂等锚点：唯一索引仅约束
    status='completed' 的行（skipped_disabled/failed 可重试多行），
    同批重放命中已完成行直接返回既有结果，不重复处理。
    逐条判定结果 / 契约②回执 / 事件信封均以 jsonb 落行内，供监控
    聚合端点（regulation-monitor）与对账巡检读取。
    """

    __tablename__ = "regulation_ingest_runs"
    __table_args__ = (
        Index(
            "uq_regulation_ingest_runs_source_run",
            "source_run_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND status = 'completed'"),
        ),
        Index("ix_regulation_ingest_runs_created_at", "created_at"),
        {"schema": "safety"},
    )

    source_run_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="ragplus 侧爬取 run_id（幂等锚点）",
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="push", server_default="push",
        comment="触发来源: push=契约①推送 | reconcile=对账巡检补处理",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="completed", server_default="completed",
        comment="completed=处理完成 | skipped_disabled=总闸关闭跳过 | failed=处理链异常",
    )
    received_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="批内候选数",
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="预去重命中数",
    )
    pending_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="待处理数（AI 超限/未判定）",
    )
    promoted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="判定相关并收录成功数",
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="判定不相关数",
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="处理错误数",
    )
    ai_tokens_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="本批 AI token 消耗",
    )
    items_result: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True,
        comment="逐条结果 [{candidate_id, action_taken, reason, ...}]",
    )
    receipts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="契约②生命周期回执结果",
    )
    event_envelope: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="regulation.updated 事件信封（成功路径）",
    )
    error_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败摘要（截断 500 字符）",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="本批处理结束时间",
    )
