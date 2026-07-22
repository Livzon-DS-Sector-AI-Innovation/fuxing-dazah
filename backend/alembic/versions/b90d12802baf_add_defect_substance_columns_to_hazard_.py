"""add defect_substance columns to hazard_reports

Revision ID: b90d12802baf
Revises: c637e4490bab
Create Date: 2026-07-01 11:19:49.215235
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b90d12802baf'
down_revision: Union[str, None] = 'c637e4490bab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.add_column(
        'hazard_reports',
        sa.Column(
            'defect_substance', sa.String(32), nullable=True,
            comment='缺陷实质评估: substantive / procedural / uncertain'
        ),
        schema='safety',
    )
    op.add_column(
        'hazard_reports',
        sa.Column(
            'defect_substance_reasoning', sa.Text(), nullable=True,
            comment='缺陷实质评估理由'
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('hazard_reports', 'defect_substance_reasoning', schema='safety')
    op.drop_column('hazard_reports', 'defect_substance', schema='safety')
