"""add scheduler_job_runs table

Revision ID: sched001a2b3c4d
Revises: e2f8c4a6d1b9
Create Date: 2026-08-10 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "sched001a2b3c4d"
down_revision: str | None = "e2f8c4a6d1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_job_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_name", sa.String(64), nullable=False,
                  comment="调度任务名（对应 SCHEDULED_JOBS.name）"),
        sa.Column("fired_date", sa.Date(), nullable=False,
                  comment="最近一次触发日期（当日已触发则不再补跑）"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.UniqueConstraint("job_name", name="uq_scheduler_job_runs_job_name"),
        schema="safety",
    )
    op.create_index(
        "ix_scheduler_job_runs_fired_date",
        "scheduler_job_runs",
        ["fired_date"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_job_runs_fired_date", table_name="scheduler_job_runs", schema="safety")
    op.drop_table("scheduler_job_runs", schema="safety")
