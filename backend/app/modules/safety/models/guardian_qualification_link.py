"""R2 监护人资格追踪 links 瘦身表（资格状态权威源）。

与 R1 alarm_hazard_links 同构的瘦身原则，但本表是**业务状态权威列**——
津贴计算联动读 qualification_status（revoked 停发），而非仅关联映射：

- 幂等：UNIQUE(record_id) WHERE is_deleted=false（Trigger 唯一约束与
  decision 防重复开工之外的第三道保险）
- 提醒计数：remind_count/last_reminded_month（每月一次共三次的月度防重）
- 资格状态：active → revoked（记 reason/at）→ restored（记确认人=Promote
  操作人，「经审核确认」留痕）
- 考核事件流：exam_history（顺序消费依据——第 N 次复审合格覆盖第 N 个
  复审节点）+ last_score_event（最新一次辨别结果）
- snapshot：触发时刻持证记录快照（追溯用）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class GuardianQualificationLink(BaseModel):
    """监护人资格状态（safety schema；执行器读写，津贴联动/REST 读）。"""

    __tablename__ = "guardian_qualification_links"
    __table_args__ = (
        Index(
            "uq_guardian_qualification_links", "record_id",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_guardian_qual_links_status", "qualification_status"),
        {"schema": "safety"},
    )

    record_id: Mapped[str] = mapped_column(
        String(64), comment="持证表 bitable record_id（幂等键）",
    )
    person_name: Mapped[str] = mapped_column(String(64), comment="姓名")
    department: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="部门",
    )
    cert_category: Mapped[str] = mapped_column(
        String(16), comment="guardian_a / guardian_b",
    )
    # ── 提醒（规则1）──
    remind_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="已发提醒次数（封顶 3）",
    )
    last_reminded_month: Mapped[str | None] = mapped_column(
        String(7), nullable=True, comment="最后提醒月份 YYYY-MM（月度防重）",
    )
    # ── 资格状态（规则2/3；津贴联动权威列）──
    qualification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
        server_default=text("'active'"),
        comment="active / revoked / restored",
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="取消资格原因（逾期未复审/考核不合格；首见事实不覆盖）",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="取消资格时间",
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="取消来源（promote 操作人/auto）",
    )
    restored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="恢复时间",
    )
    confirmed_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="恢复确认人（Promote 操作人，「经审核确认」留痕）",
    )
    # ── 节点快照（最近判定）──
    current_node: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="最近判定节点 node_key",
    )
    node_deadline: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="最近判定节点截止日",
    )
    # ── 考核事件流（规则4；顺序消费依据）──
    exam_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
        comment="考核事件流 [{exam_type, passed, exam_date, discriminated}]",
    )
    last_score_event: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="最新一次考核事件（含辨别结果）",
    )
    # ── 关联与追溯 ──
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 superagent.agent_tasks.id",
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
        comment="触发时刻持证记录快照",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="执行器失败留痕（重试成功后清空）",
    )
    # is_deleted 由 BaseModel 提供（软删惯例；部分唯一索引谓词引用它）
