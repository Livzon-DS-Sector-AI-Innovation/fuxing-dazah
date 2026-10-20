"""safety facilities 三表（校验任务/通知批次/任务事件流，facilities-p1）

DESIGN §3.2：校验任务闭环核心实体。facility_check_tasks 唯一
(biz_type, ledger_key, due_date) partial = 派发幂等；facility_notice_batches
部门唯一 open partial = 每部门至多一张滚动批次卡；facility_task_events
append-only 审计。无种子。

Revision ID: f1a2b3c4d5e6
Revises: c2d6e8f0a4b7
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "c2d6e8f0a4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table(
        "facility_check_tasks",
        sa.Column(
            "biz_type", sa.String(length=32), nullable=False,
            comment="accessory / fire_equipment / special_equipment",
        ),
        sa.Column(
            "ledger_key", sa.String(length=64), nullable=False,
            comment="台账行标识（feishu_record_id，稳定）",
        ),
        sa.Column("equipment_no", sa.String(length=255), nullable=True),
        sa.Column("equipment_name", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column(
            "task_kind", sa.String(length=32), nullable=False,
            comment="任务文案：校验 / 检查 / 定期检验",
        ),
        sa.Column("due_date", sa.Date(), nullable=False, comment="=台账锚点日期"),
        sa.Column("lead_days", sa.Integer(), nullable=False, comment="派发提前量快照"),
        sa.Column(
            "status", sa.String(length=16), server_default="issued", nullable=False,
            comment="issued / closed / cancelled",
        ),
        sa.Column("assignee_open_id", sa.String(length=64), nullable=True),
        sa.Column("assignee_name", sa.String(length=64), nullable=True),
        sa.Column(
            "batch_id", UUID(as_uuid=True), nullable=True,
            comment="所属通知批次（合并发送锚点）",
        ),
        sa.Column(
            "group_key", sa.String(length=128), nullable=False,
            comment="部门内分组标签（类别标签×工作性质）",
        ),
        sa.Column(
            "task_subtype", sa.String(length=32), nullable=False,
            comment="工作性质：校验/检查/换药/报废更换/定期检验",
        ),
        sa.Column(
            "anchor_at_dispatch", sa.Date(), nullable=False,
            comment="派发时的锚点原值（闭环判定基准）",
        ),
        sa.Column(
            "issued_on", sa.Date(), nullable=False,
            comment="派发日（北京日；「上次日期≥派发日」判定锚）",
        ),
        sa.Column(
            "closed_trigger", sa.String(length=16), nullable=True,
            comment="event(表格变更) / poll(每日对账) / manual",
        ),
        sa.Column(
            "closed_reason", sa.Text(), nullable=True,
            comment="manual 关闭/取消必填原因；自动闭环可空",
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "closed_by", sa.String(length=64), nullable=True,
            comment="manual 操作者（open_id 或 system）",
        ),
        sa.Column(
            "remind_count", sa.Integer(), server_default="0", nullable=False,
            comment="升级提醒计数",
        ),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_facility_check_tasks_biz_key_due",
        "facility_check_tasks",
        ["biz_type", "ledger_key", "due_date"],
        schema="safety",
        unique=True,
        # 幂等唯一键只约束在办任务：cancelled/closed 不阻塞同物同周期重派
        postgresql_where=sa.text("is_deleted = false and status = 'issued'"),
    )
    op.create_index(
        "ix_facility_check_tasks_status_due",
        "facility_check_tasks",
        ["status", "due_date"],
        schema="safety",
    )
    op.create_index(
        "ix_facility_check_tasks_department",
        "facility_check_tasks",
        ["department"],
        schema="safety",
    )
    op.create_index(
        "ix_facility_check_tasks_batch",
        "facility_check_tasks",
        ["batch_id"],
        schema="safety",
    )

    op.create_table(
        "facility_notice_batches",
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column(
            "card_message_id", sa.String(length=64), nullable=True,
            comment="滚动批次卡 message_id（原地 PATCH 锚点）",
        ),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="open", nullable=False,
            comment="open（滚动更新中）/ archived（全闭环归档停更）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_facility_notice_batches_dept_open",
        "facility_notice_batches",
        ["department"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("status = 'open' and is_deleted = false"),
    )

    op.create_table(
        "facility_task_events",
        sa.Column(
            "task_id", UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "event_type", sa.String(length=16), nullable=False,
            comment="issued / closed / cancelled / reminded / escalated / reopened",
        ),
        sa.Column(
            "operator", sa.String(length=64), nullable=True,
            comment="事件操作者（open_id / system / event）",
        ),
        sa.Column(
            "closed_trigger", sa.String(length=16), nullable=True,
            comment="closed/cancelled 事件的触发通道 event/poll/manual",
        ),
        sa.Column(
            "payload", JSONB(), nullable=True,
            comment="载荷摘要；closed 事件记锚点前后值",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["safety.facility_check_tasks.id"],
        ),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_facility_task_events_task_created",
        "facility_task_events",
        ["task_id", "created_at"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_facility_task_events_task_created",
        table_name="facility_task_events", schema="safety",
    )
    op.drop_table("facility_task_events", schema="safety")
    op.drop_index(
        "uq_facility_notice_batches_dept_open",
        table_name="facility_notice_batches", schema="safety",
    )
    op.drop_table("facility_notice_batches", schema="safety")
    op.drop_index(
        "ix_facility_check_tasks_batch",
        table_name="facility_check_tasks", schema="safety",
    )
    op.drop_index(
        "ix_facility_check_tasks_department",
        table_name="facility_check_tasks", schema="safety",
    )
    op.drop_index(
        "ix_facility_check_tasks_status_due",
        table_name="facility_check_tasks", schema="safety",
    )
    op.drop_index(
        "uq_facility_check_tasks_biz_key_due",
        table_name="facility_check_tasks", schema="safety",
    )
    op.drop_table("facility_check_tasks", schema="safety")
