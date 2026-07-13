"""add actual_department to employees

Revision ID: 17fda41cfdd0
Revises: 16fda41cfdd9
Create Date: 2026-07-13 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '17fda41cfdd0'
down_revision: Union[str, None] = '16fda41cfdd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('actual_department', sa.String(64), nullable=True, comment='实际部门'), schema='hr')


def downgrade() -> None:
    op.drop_column('employees', 'actual_department', schema='hr')
