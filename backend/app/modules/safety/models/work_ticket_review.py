"""Safety ORM models."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 作业票审核 ====================


class WorkTicketReview(BaseModel):
    """作业票审核摘要表（每日标准 8 类作业票规则审核结果）。"""

    __tablename__ = "work_ticket_reviews"
    __table_args__ = (
        Index(
            "uq_work_ticket_reviews_date",
            "date",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_work_ticket_reviews_date", "date"),
        {"schema": "safety"},
    )

    date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="审核日期（作业日期，Asia/Shanghai）"
    )
    total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="当日拉取到的标准 8 类作业票总数",
    )
    reviewed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="已具备开始时间、纳入规则审核的票数",
    )
    violation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="违规票数（含违规条数的票数，非条数）",
    )
    compliant_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="合格票数（有开始时间且无任何违规）",
    )
    data_insufficient: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="数据不足票数（缺开始时间/关键字段，审核窗口未满足）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", server_default="success",
        comment="审核状态: pending/success/failed",
    )
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="当日平台原始工作流数据快照",
    )
    report_markdown: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="生成的可读 Markdown 报告",
    )
    pushed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="是否已推送群",
    )
    push_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书卡片 message_id",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间",
    )


class WorkTicketReviewViolation(BaseModel):
    """作业票审核逐票违规明细表。"""

    __tablename__ = "work_ticket_review_violations"
    __table_args__ = (
        Index("ix_wt_review_violations_review_id", "review_id"),
        Index("ix_wt_review_violations_ticket_no", "ticket_no"),
        Index("ix_wt_review_violations_rule_no", "rule_no"),
        {"schema": "safety"},
    )

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="逻辑外键 → work_ticket_reviews.id（不建物理 FK）",
    )
    ticket_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="作业票号")
    ticket_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型: hot_work/confined_space/height_work/..."
    )
    rule_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="规则编号: TIME_ORDER/GAS_VALIDITY/DURATION/GAS_INTERVAL"
    )
    rule_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="规则中文名")
    detail: Mapped[str] = mapped_column(Text, nullable=False, comment="违规/不适用描述")
    key_times: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="关键时间点 {申请/审批/开始/结束/验收/气体分析等}"
    )
    not_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="true 表示该规则对该票「不适用」而非违规",
    )


