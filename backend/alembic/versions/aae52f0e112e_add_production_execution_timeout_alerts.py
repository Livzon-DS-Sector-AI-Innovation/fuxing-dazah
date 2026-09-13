"""add production execution timeout alerts

Revision ID: aae52f0e112e
Revises: 286c8ec29dd9
Create Date: 2026-09-13 14:52:52.533451
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aae52f0e112e"
down_revision: str | None = "286c8ec29dd9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # production 是既有业务 schema；IF NOT EXISTS 使空库/独立迁移执行安全。
    op.execute("CREATE SCHEMA IF NOT EXISTS production")
    op.create_table(
        "node_execution_timeout_alerts",
        sa.Column("execution_id", sa.Uuid(), nullable=False, comment="工序执行实例"),
        sa.Column("product_id", sa.Uuid(), nullable=False, comment="估算时的产品快照"),
        sa.Column(
            "route_id", sa.Uuid(), nullable=False, comment="估算时的路线版本快照"
        ),
        sa.Column(
            "node_id", sa.Uuid(), nullable=False, comment="估算时的当前路线节点快照"
        ),
        sa.Column(
            "estimated_duration_seconds",
            sa.Float(),
            nullable=False,
            comment="工序预计时长（秒）",
        ),
        sa.Column(
            "estimate_method",
            sa.String(length=20),
            server_default="p80",
            nullable=False,
            comment="估算方法",
        ),
        sa.Column(
            "estimate_sample_count",
            sa.Integer(),
            nullable=False,
            comment="估算使用的有效样本数",
        ),
        sa.Column(
            "estimate_window_days",
            sa.Integer(),
            server_default="180",
            nullable=False,
            comment="实际采用的历史窗口天数（近180天不足样本时回退365天）",
        ),
        sa.Column(
            "estimate_version",
            sa.String(length=20),
            server_default="v3",
            nullable=False,
            comment="估算口径版本",
        ),
        sa.Column(
            "expected_finish_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="开始时物化的预计完成时间",
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="下次可扫描/重试时间",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
            comment="pending/sending/sent/resolved/failed",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="通知尝试次数",
        ),
        sa.Column(
            "lease_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="多实例抢占租约到期时间",
        ),
        sa.Column(
            "lease_token",
            sa.String(length=64),
            nullable=True,
            comment="本次发送租约令牌，防止过期 worker 覆盖状态",
        ),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="首次判定超时的时间",
        ),
        sa.Column(
            "notified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="成功发送通知的时间",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="监控关闭时间",
        ),
        sa.Column(
            "resolution_reason",
            sa.String(length=100),
            nullable=True,
            comment="关闭原因",
        ),
        sa.Column(
            "notified_recipient_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="通知接收人 user_id 快照",
        ),
        sa.Column(
            "last_error", sa.Text(), nullable=True, comment="最近一次通知失败原因"
        ),
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
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'resolved', 'failed')",
            name="ck_production_node_execution_timeout_alerts_status",
        ),
        sa.CheckConstraint(
            "estimated_duration_seconds > 0",
            name="ck_production_node_execution_timeout_alerts_duration",
        ),
        schema="production",
    )
    op.create_index(
        "uq_production_node_execution_timeout_alerts_execution",
        "node_execution_timeout_alerts",
        ["execution_id"],
        unique=True,
        schema="production",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_production_node_execution_timeout_alerts_due",
        "node_execution_timeout_alerts",
        ["next_attempt_at", "expected_finish_at"],
        unique=False,
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status IN ('pending', 'sending')"
        ),
    )
    op.create_index(
        "ix_production_node_execution_timeout_alerts_reconcile",
        "node_execution_timeout_alerts",
        ["updated_at", "execution_id"],
        unique=False,
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status IN ('pending', 'sending', 'sent', 'failed')"
        ),
    )
    # 基线聚合的历史过滤索引：仅覆盖首次已完成执行，降低开始工序时的扫描量。
    op.create_index(
        "ix_production_node_executions_timeout_baseline",
        "node_executions",
        ["node_id", "started_at", "batch_id"],
        unique=False,
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status = 'completed' AND execution_seq = 1"
        ),
    )
    op.create_index(
        "ix_production_batches_timeout_scope",
        "batches",
        ["product_id", "route_id", "id"],
        unique=False,
        schema="production",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_production_batches_timeout_scope",
        table_name="batches",
        schema="production",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index(
        "ix_production_node_executions_timeout_baseline",
        table_name="node_executions",
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status = 'completed' AND execution_seq = 1"
        ),
    )
    op.drop_index(
        "ix_production_node_execution_timeout_alerts_reconcile",
        table_name="node_execution_timeout_alerts",
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status IN ('pending', 'sending', 'sent', 'failed')"
        ),
    )
    op.drop_index(
        "ix_production_node_execution_timeout_alerts_due",
        table_name="node_execution_timeout_alerts",
        schema="production",
        postgresql_where=sa.text(
            "is_deleted = false AND status IN ('pending', 'sending')"
        ),
    )
    op.drop_index(
        "uq_production_node_execution_timeout_alerts_execution",
        table_name="node_execution_timeout_alerts",
        schema="production",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("node_execution_timeout_alerts", schema="production")
