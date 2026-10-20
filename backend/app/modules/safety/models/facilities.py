"""安全设备设施管理 ORM（facilities-p1）。

三表分工（DESIGN §3.2）：
- FacilityCheckTask：校验任务核心实体。唯一 (biz_type, ledger_key, due_date)
  = 同物同周期只有一个任务（派发幂等核心）；issued_on 为「上次日期≥派发日」
  闭环判定的比较锚。
- FacilityNoticeBatch：通知批次（合并发送与追踪锚点）。部门唯一 open
  （partial unique）：每部门至多一张进行中滚动卡。
- FacilityTaskEvent：append-only 审计事件流（closed 事件 payload 记
  closed_trigger 与锚点前后值）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

TASK_STATUS_ISSUED = "issued"
TASK_STATUS_CLOSED = "closed"
TASK_STATUS_CANCELLED = "cancelled"

TRIGGER_EVENT = "event"
TRIGGER_POLL = "poll"
TRIGGER_MANUAL = "manual"


class FacilityCheckTask(BaseModel):
    """校验任务（三台账共用，biz_type 区分）。"""

    __tablename__ = "facility_check_tasks"
    __table_args__ = (
        # 幂等唯一键只约束在办任务（DESIGN §4.2「已有 … 且 status=issued 的跳过」）：
        # cancelled（行失效）/closed（锚点已前移，重派时 due 自然不同）不得阻塞
        # 同物同周期重派——「停用→取消→再启用」须能重新派发
        Index(
            "uq_facility_check_tasks_biz_key_due",
            "biz_type", "ledger_key", "due_date",
            unique=True,
            postgresql_where=text("is_deleted = false and status = 'issued'"),
        ),
        Index("ix_facility_check_tasks_status_due", "status", "due_date"),
        Index("ix_facility_check_tasks_department", "department"),
        Index("ix_facility_check_tasks_batch", "batch_id"),
        {"schema": "safety"},
    )

    biz_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="accessory / fire_equipment / special_equipment"
    )
    ledger_key: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="台账行标识（feishu_record_id，稳定）"
    )
    # 冗余快照（任务自包含，台账行后续变更不改变已派任务语义）
    equipment_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    task_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="任务文案：校验 / 检查 / 定期检验"
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False, comment="=台账锚点日期")
    lead_days: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="派发提前量快照"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TASK_STATUS_ISSUED,
        server_default=TASK_STATUS_ISSUED, comment="issued / closed / cancelled",
    )
    assignee_open_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    batch_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="所属通知批次（合并发送锚点）"
    )
    group_key: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="部门内分组标签（类别标签×工作性质）"
    )
    task_subtype: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="工作性质：校验/检查/换药/报废更换/定期检验"
    )

    anchor_at_dispatch: Mapped[date] = mapped_column(
        Date, nullable=False, comment="派发时的锚点原值（闭环判定基准）"
    )
    issued_on: Mapped[date] = mapped_column(
        Date, nullable=False, comment="派发日（北京日；「上次日期≥派发日」判定锚）"
    )

    closed_trigger: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="event(表格变更) / poll(每日对账) / manual"
    )
    closed_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="manual 关闭/取消必填原因；自动闭环可空"
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="manual 操作者（open_id 或 system）"
    )

    remind_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="升级提醒计数"
    )
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FacilityNoticeBatch(BaseModel):
    """通知批次（滚动批次卡锚点：每部门至多一张 open 卡）。"""

    __tablename__ = "facility_notice_batches"
    __table_args__ = (
        Index(
            "uq_facility_notice_batches_dept_open",
            "department",
            unique=True,
            postgresql_where=text("status = 'open' and is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    department: Mapped[str] = mapped_column(String(64), nullable=False)
    card_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="滚动批次卡 message_id（原地 PATCH 锚点）"
    )
    total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
        comment="open（滚动更新中）/ archived（全闭环归档停更）",
    )


class FacilityTaskEvent(BaseModel):
    """任务事件流（append-only 审计）。"""

    __tablename__ = "facility_task_events"
    __table_args__ = (
        Index("ix_facility_task_events_task_created", "task_id", "created_at"),
        {"schema": "safety"},
    )

    task_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.facility_check_tasks.id"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="issued / closed / cancelled / reminded / escalated / reopened",
    )
    operator: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="事件操作者（open_id / system / event）"
    )
    closed_trigger: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="closed/cancelled 事件的触发通道 event/poll/manual"
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        comment="载荷摘要；closed 事件记锚点前后值",
    )
