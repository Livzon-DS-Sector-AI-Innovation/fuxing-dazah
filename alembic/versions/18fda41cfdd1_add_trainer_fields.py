"""add is_level1 and admin to trainers

Revision ID: 18fda41cfdd1
Revises: c3e4ebb6a363
Create Date: 2026-07-13 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '18fda41cfdd1'
down_revision: Union[str, None] = 'c3e4ebb6a363'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trainers', sa.Column('is_level1', sa.String(16), nullable=True, comment='是否一级培训师'), schema='hr')
    op.add_column('trainers', sa.Column('admin', sa.String(64), nullable=True, comment='培训管理员'), schema='hr')


def downgrade() -> None:
    op.drop_column('trainers', 'admin', schema='hr')
    op.drop_column('trainers', 'is_level1', schema='hr')
