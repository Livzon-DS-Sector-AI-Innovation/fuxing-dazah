"""warehouse: 库存分析定档表 analysis_reports（直读改造 2026-11-04）

Revision ID: d4e7a1c35b82
Revises: c2d5e8f01a93
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4e7a1c35b82"
down_revision = "c2d5e8f01a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False,
                  comment="分析业务日（北京时区）"),
        sa.Column("summary", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb"),
                  comment="分析结果 JSON（KPI/分布/Top/预警）"),
        sa.Column("trigger", sa.String(16), nullable=False,
                  server_default="scheduled", comment="触发方式：scheduled/manual"),
        sa.Column("duration_ms", sa.Integer(), nullable=False,
                  server_default="0", comment="生成耗时毫秒"),
        sa.Column("created_by", postgresql.UUID(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index(
            "uq_warehouse_analysis_reports_date", "report_date", unique=True,
            postgresql_where=sa.text("is_deleted = false"),
        ),
        schema="warehouse",
    )


def downgrade() -> None:
    op.drop_table("analysis_reports", schema="warehouse")
