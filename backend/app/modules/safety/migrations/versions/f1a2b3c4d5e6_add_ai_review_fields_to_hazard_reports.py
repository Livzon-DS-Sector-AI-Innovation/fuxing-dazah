"""add ai_review fields to hazard_reports

Revision ID: f1a2b3c4d5e6
Revises: e1k2m3n4o5p6
Create Date: 2026-06-24 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'e1k2m3n4o5p6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": schema, "table": table, "column": column},
    ).first()
    return row is not None


def _add_column_if_missing(table: str, column: sa.Column, *, schema: str) -> None:
    if not _column_exists(table, column.name, schema):
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    _add_column_if_missing(
        "hazard_reports",
        sa.Column(
            "ai_review_result",
            JSONB,
            nullable=True,
            comment="AI 整改初审结果 JSON（RectificationReviewOutput 完整输出）"
        ),
        schema="safety",
    )
    _add_column_if_missing(
        "hazard_reports",
        sa.Column(
            "ai_review_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
            comment="AI 初审状态: pending / processing / completed / failed"
        ),
        schema="safety",
    )
    _add_column_if_missing(
        "hazard_reports",
        sa.Column(
            "ai_review_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="AI 初审完成时间"
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "ai_review_completed_at", schema="safety")
    op.drop_column("hazard_reports", "ai_review_status", schema="safety")
    op.drop_column("hazard_reports", "ai_review_result", schema="safety")
