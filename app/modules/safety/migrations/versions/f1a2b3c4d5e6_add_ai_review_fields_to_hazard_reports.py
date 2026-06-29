"""add ai_review fields to hazard_reports

Revision ID: f1a2b3c4d5e6
Revises: e1k2m3n4o5p6
Create Date: 2026-06-24 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e1k2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "ai_review_result",
            JSONB,
            nullable=True,
            comment="AI 整改初审结果 JSON（RectificationReviewOutput 完整输出）"
        ),
        schema="safety",
    )
    op.add_column(
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
    op.add_column(
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
