"""add scheduler_job_runs status columns

为定时任务失败重试/恢复补发机制扩展 scheduler_job_runs：
- status:          success / failed（当天任务最终状态，success 才去重不再跑）
- last_attempt_at: 最近一次尝试时间（用于失败重试退避）
- attempt_count:   当天连续失败次数（达阈值触发告警）
- alerted:         当天是否已发送失败告警（避免重复告警轰炸）

Revision ID: sched002a3b4c5d
Revises: 7ab77b587f42
Create Date: 2026-08-14 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "sched002a3b4c5d"
down_revision: str | None = "7ab77b587f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduler_job_runs",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="success",
            comment="当天任务状态: success=已成功(去重不再跑) / failed=失败(待重试补发)",
        ),
        schema="safety",
    )
    op.add_column(
        "scheduler_job_runs",
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次执行尝试时间（用于失败重试退避间隔判断）",
        ),
        schema="safety",
    )
    op.add_column(
        "scheduler_job_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当天连续失败次数（成功时清零，达阈值触发失败告警）",
        ),
        schema="safety",
    )
    op.add_column(
        "scheduler_job_runs",
        sa.Column(
            "alerted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="当天是否已发送失败告警（成功后重置）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("scheduler_job_runs", "alerted", schema="safety")
    op.drop_column("scheduler_job_runs", "attempt_count", schema="safety")
    op.drop_column("scheduler_job_runs", "last_attempt_at", schema="safety")
    op.drop_column("scheduler_job_runs", "status", schema="safety")
