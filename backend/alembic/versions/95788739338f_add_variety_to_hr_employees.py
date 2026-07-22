"""add variety to hr_employees

Revision ID: 95788739338f
Revises: e22654fa1b3c
Create Date: 2026-07-08 15:45:57.421681
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '95788739338f'
down_revision: Union[str, None] = 'e22654fa1b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('variety', sa.String(length=64), nullable=True, comment='品种'), schema='hr')


def downgrade() -> None:
    op.drop_column('employees', 'variety', schema='hr')
