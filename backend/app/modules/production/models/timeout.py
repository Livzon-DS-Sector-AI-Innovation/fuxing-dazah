"""工序执行超时监控 ORM。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class NodeExecutionTimeoutAlert(BaseModel):
    """工序开始时生成的超时基线快照及通知状态。

    扫描任务只消费本表中已经物化的 ``expected_finish_at``，不会在扫描时
    重新计算历史分位数，避免进行中的工序因样本变化而移动截止时间。
    """

    __tablename__ = "node_execution_timeout_alerts"
    __table_args__ = (
        Index(
            "uq_production_node_execution_timeout_alerts_execution",
            "execution_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_production_node_execution_timeout_alerts_due",
            "next_attempt_at",
            "expected_finish_at",
            postgresql_where=text(
                "is_deleted = false AND status IN ('pending', 'sending')"
            ),
        ),
        Index(
            "ix_production_node_execution_timeout_alerts_reconcile",
            "updated_at",
            "execution_id",
            postgresql_where=text(
                "is_deleted = false AND status IN ('pending', 'sending', 'sent', 'failed')"
            ),
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'resolved', 'failed')",
            name="ck_production_node_execution_timeout_alerts_status",
        ),
        CheckConstraint(
            "estimated_duration_seconds > 0",
            name="ck_production_node_execution_timeout_alerts_duration",
        ),
        {"schema": "production"},
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(comment="工序执行实例")
    product_id: Mapped[uuid.UUID] = mapped_column(comment="估算时的产品快照")
    route_id: Mapped[uuid.UUID] = mapped_column(comment="估算时的路线版本快照")
    node_id: Mapped[uuid.UUID] = mapped_column(comment="估算时的当前路线节点快照")

    estimated_duration_seconds: Mapped[float] = mapped_column(
        Float, comment="工序预计时长（秒）"
    )
    estimate_method: Mapped[str] = mapped_column(
        String(20), default="p80", server_default="p80", comment="估算方法"
    )
    estimate_sample_count: Mapped[int] = mapped_column(
        Integer, comment="估算使用的有效样本数"
    )
    estimate_window_days: Mapped[int] = mapped_column(
        Integer,
        default=180,
        server_default="180",
        comment="实际采用的历史窗口天数（近180天不足样本时回退365天）",
    )
    estimate_version: Mapped[str] = mapped_column(
        String(20), default="v3", server_default="v3", comment="估算口径版本"
    )

    expected_finish_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="开始时物化的预计完成时间"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="下次可扫描/重试时间"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending",
        comment="pending/sending/sent/resolved/failed",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="通知尝试次数"
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="多实例抢占租约到期时间"
    )
    lease_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="本次发送租约令牌，防止过期 worker 覆盖状态"
    )
    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="首次判定超时的时间"
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="成功进入发送管线的时间"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="监控关闭时间"
    )
    resolution_reason: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="关闭原因"
    )
    notified_recipient_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="通知接收人 user_id 快照"
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次通知失败原因"
    )
