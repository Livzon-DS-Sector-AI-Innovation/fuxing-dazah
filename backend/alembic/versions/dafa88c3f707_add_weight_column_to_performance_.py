"""add weight column to performance_category_scores

Revision ID: dafa88c3f707
Revises: 89f4118d713f
Create Date: 2026-08-04 11:36:10.666588
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dafa88c3f707'
down_revision: Union[str, None] = '89f4118d713f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('performance_category_scores',
        sa.Column('weight', sa.Float(), nullable=False, server_default='0',
                  comment='该部门此项目权重(%)'),
        schema='hr')


def downgrade() -> None:
    op.drop_column('performance_category_scores', 'weight', schema='hr')
