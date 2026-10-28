"""quality add plan assignments

Revision ID: fbd83416e8e7
Revises: 54b731ca811d
Create Date: 2026-10-28 17:31:43.466244
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fbd83416e8e7'
down_revision: str | None = '54b731ca811d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 请检计划排班：计划级 SOP→负责人（建任务时拷贝到任务分工）
    op.add_column(
        "quality_inspection_plans",
        sa.Column("assignments", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="排班 [{\"sop_no\": ..., \"assignee_id\": ...}]"),
        schema="quality",
    )


def downgrade() -> None:
    op.drop_column("quality_inspection_plans", "assignments", schema="quality")
