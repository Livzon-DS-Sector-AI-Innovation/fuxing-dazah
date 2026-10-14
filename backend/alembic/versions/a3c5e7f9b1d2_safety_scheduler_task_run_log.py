"""safety scheduler_task_run_log（定时任务运行日志，Agent 任务运行中心）

append-only：每次调度尝试一行（成功/失败/超时，含耗时与错误摘要）。
与 scheduler_job_runs（每任务一行去重表）分工——去重/重试/告警走旧表，
本表只服务监督页展示（3.0 四期 1-D）。无种子。

Revision ID: a3c5e7f9b1d2
Revises: m8b1c3d5e7f9
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3c5e7f9b1d2"
down_revision: str | None = "m8b1c3d5e7f9"
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
        "scheduler_task_run_log",
        sa.Column(
            "job_name",
            sa.String(length=64),
            nullable=False,
            comment="调度任务名（对应 SCHEDULED_JOBS.name）",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="本次尝试开始时间（UTC）",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="本次尝试结束时间（UTC）",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="success",
            nullable=False,
            comment="success=成功 / failed=失败或超时",
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="耗时（毫秒）"),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
            comment="失败摘要（异常类型+消息，截断 500 字符）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_scheduler_task_run_log_job_started",
        "scheduler_task_run_log",
        ["job_name", "started_at"],
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduler_task_run_log_job_started",
        table_name="scheduler_task_run_log",
        schema="safety",
    )
    op.drop_table("scheduler_task_run_log", schema="safety")
