"""add supervision_level to hazard_reports

Revision ID: 314f6e376dc1
Revises: n2o3p4q5r6s7
Create Date: 2026-07-28 10:40:42.779969
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '314f6e376dc1'
down_revision: str | None = 'n2o3p4q5r6s7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "supervision_level",
            sa.String(16),
            nullable=True,
            comment="督办等级: overdue(超期) / warning(预警) / normal(一般) / closed(已关闭)",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "supervision_level", schema="safety")
