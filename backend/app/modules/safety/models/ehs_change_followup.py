"""EHS 变更周度督办 ORM —— rounds / dispatches / items 三表（DESIGN §7）。

一轮 = 一个周五：落库而非 Redis 的三个理由——周一要拿周五进展快照比对、
要防服务重启重发（dispatch.send_status 幂等补发）、要能事后查
「哪项变更第几周还没更新」（items.outcome 历史可溯）。

写侧约定：系统对变更表只追加写「变更最新具体进展」一列；本域表只由
周五/周一任务与卡片回调写入，回调写库幂等（重复点按钮不重复计数）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

# 轮次状态：sending=发送中（有卡未发完） / sent=周五收口 / summarized=周一总结完
ROUND_SENDING = "sending"
ROUND_SENT = "sent"
ROUND_SUMMARIZED = "summarized"

# 卡片发送状态
DISPATCH_PENDING = "pending"
DISPATCH_SENT = "sent"
DISPATCH_FAILED = "failed"
DISPATCH_NO_RECIPIENT = "no_recipient"   # 部门未配置安全员
DISPATCH_UNRESOLVED = "unresolved"       # 安全员解析不到 open_id

# 安全员反馈：空=未反馈 / unchanged=点了「进展不变，无需更新」
RESPONSE_UNCHANGED = "unchanged"

# 周一单项判定（DESIGN §5 顺序命中即止）
OUTCOME_CLOSED = "closed"          # 本周已关闭，不进三类
OUTCOME_UPDATED = "updated"        # ③ 更新
OUTCOME_UNCHANGED = "unchanged"    # ② 进展不变，无需更新
OUTCOME_NOT_UPDATED = "not_updated"  # ① 未更新


class EhsChangeFollowupRound(BaseModel):
    """一轮周度督办（一个周五一行）。"""

    __tablename__ = "ehs_change_followup_rounds"
    __table_args__ = (
        UniqueConstraint("year", "week_no", name="uq_ehs_change_followup_rounds_week"),
        Index("ix_ehs_change_followup_rounds_fired_on", "fired_on"),
        {"schema": "safety"},
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="ISO 年")
    week_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="ISO 周号")
    fired_on: Mapped[date] = mapped_column(Date, nullable=False, comment="触发日（周五）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ROUND_SENDING,
        comment="sending/sent/summarized",
    )
    stats: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="轮次统计快照（周五/周一各写一次）",
    )


class EhsChangeFollowupDispatch(BaseModel):
    """一位安全员的一张周五卡。"""

    __tablename__ = "ehs_change_followup_dispatches"
    __table_args__ = (
        Index("ix_ehs_change_followup_dispatches_round", "round_id"),
        {"schema": "safety"},
    )

    round_id: Mapped[str] = mapped_column(
        ForeignKey("safety.ehs_change_followup_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    officer_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="分管安全员姓名")
    officer_open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="安全应用作用域 open_id（发送锚点）",
    )
    officer_user_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="租户级 user_id（identity 来源时用它发送）",
    )
    departments: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="覆盖部门（逗号分隔；同人跨部门合一卡）",
    )
    change_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="卡内变更项数")

    send_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DISPATCH_PENDING,
        comment="pending/sent/failed/unresolved",
    )
    message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="周五卡 message_id（om_…，PATCH 锚点）",
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="空=未反馈；unchanged=点了「进展不变」",
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="周一判出的该安全员主分类（updated/unchanged/not_updated）",
    )


class EhsChangeFollowupItem(BaseModel):
    """一轮里的一项变更（周五快照 + 周一判定）。"""

    __tablename__ = "ehs_change_followup_items"
    __table_args__ = (
        UniqueConstraint("round_id", "record_id", name="uq_ehs_change_followup_items_round_record"),
        Index("ix_ehs_change_followup_items_record", "record_id"),
        {"schema": "safety"},
    )

    round_id: Mapped[str] = mapped_column(
        ForeignKey("safety.ehs_change_followup_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    dispatch_id: Mapped[str | None] = mapped_column(
        ForeignKey("safety.ehs_change_followup_dispatches.id", ondelete="SET NULL"),
        nullable=True, comment="无人可发（部门未配安全员）时为空",
    )

    record_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="审批表 record_id")
    change_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="变更申请编号")
    title: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="变更名称")
    department: Mapped[str] = mapped_column(String(128), nullable=False, comment="申请部门（多部门逗号分隔）")

    # ── 周五快照（卡面展示 + 周一比对基线）──
    status_shown: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="「变更状态」原样留存（仅展示，不参与关闭判定）",
    )
    acceptance_note: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="排除项标注（验收单审批中/已撤回/疑似覆盖/未找到）",
    )
    progress_friday: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="周五时点「变更最新具体进展」全文",
    )
    expected_start: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="预计实施日期 YYYY-MM-DD",
    )
    approval_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="审批详情 applink",
    )
    nag_weeks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="第 N 周督办（历史轮次同 record 计数+1）",
    )

    # ── 卡片提交回填（幂等：重复提交以最后一次为准）──
    replied_progress: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次卡片提交的进展原文",
    )
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_by: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="提交人标识")

    # ── 周一判定 ──
    progress_monday: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="周一复查时点进展全文（未复查为空）",
    )
    outcome: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="closed/updated/unchanged/not_updated（周一写入）",
    )
