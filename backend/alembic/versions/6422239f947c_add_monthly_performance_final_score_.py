"""add monthly performance final_score column

部门加权总分（多项目评分保存后自动计算）。

Revision ID: 6422239f947c
Revises: 957424208cea
Create Date: 2026-08-27 12:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6422239f947c'
down_revision: str | None = '957424208cea'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'monthly_performance_evaluations',
        sa.Column('final_score', sa.Float(), nullable=True,
                  comment='部门加权总分（多项目评分保存后自动计算）'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('monthly_performance_evaluations', 'final_score', schema='hr')
