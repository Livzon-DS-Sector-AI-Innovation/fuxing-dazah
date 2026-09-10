"""add scheduler_task_configs and scheduler_config_audits tables

Revision ID: sched003a1b2c3d4
Revises: d7c5bc5fbaa8
Create Date: 2026-08-27 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "sched003a1b2c3d4"
down_revision: str | None = "d7c5bc5fbaa8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_task_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_name",
            sa.String(64),
            nullable=False,
            comment="调度任务名（对应 SCHEDULED_JOBS.name）",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否启用",
        ),
        sa.Column("hour", sa.Integer(), nullable=True, comment="执行小时 0-23"),
        sa.Column("minute", sa.Integer(), nullable=True, comment="执行分钟 0-59"),
        sa.Column(
            "dow",
            sa.Integer(),
            nullable=True,
            comment="星期 0-6（周一-周日），NULL=每天",
        ),
        sa.Column(
            "target_chat_id", sa.String(128), nullable=True, comment="飞书群聊 chat_id"
        ),
        sa.Column(
            "target_chat_name", sa.String(128), nullable=True, comment="群名（冗余，前端展示）"
        ),
        sa.Column(
            "retry_until_hour", sa.Integer(), nullable=True, comment="补发窗口截止小时"
        ),
        sa.Column(
            "retry_until_minute", sa.Integer(), nullable=True, comment="补发窗口截止分钟"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("scheduler_task_configs_pkey")),
        schema="safety",
        comment="定时任务配置覆写表（与 SCHEDULED_JOBS 按 job_name 匹配，NULL=使用代码默认值）",
    )
    op.create_index(
        "uq_scheduler_task_configs_job_name",
        "scheduler_task_configs",
        ["job_name"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.create_table(
        "scheduler_config_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_name",
            sa.String(64),
            nullable=False,
            comment="任务名（对应 SCHEDULED_JOBS.name）",
        ),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="动作: update/enable/disable/run 等",
        ),
        sa.Column(
            "before_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更前配置（compact）",
        ),
        sa.Column(
            "after_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更后配置（compact）",
        ),
        sa.Column(
            "operator_name",
            sa.String(128),
            nullable=True,
            comment="操作人（当前用户 name，无则 None）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("scheduler_config_audits_pkey")),
        schema="safety",
        comment="定时任务配置变更审计表（append-only）",
    )
    op.create_index(
        "idx_scheduler_config_audits_job_created",
        "scheduler_config_audits",
        ["job_name", "created_at"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_scheduler_config_audits_job_created",
        table_name="scheduler_config_audits",
        schema="safety",
    )
    op.drop_table("scheduler_config_audits", schema="safety")
    op.drop_index(
        "uq_scheduler_task_configs_job_name",
        table_name="scheduler_task_configs",
        schema="safety",
    )
    op.drop_table("scheduler_task_configs", schema="safety")
