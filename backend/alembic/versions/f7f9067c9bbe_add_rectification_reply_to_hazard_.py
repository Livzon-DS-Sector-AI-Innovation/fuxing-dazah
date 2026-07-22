"""add rectification_reply to hazard_reports

Revision ID: f7f9067c9bbe
Revises: 8a1b2c3d4e5f
Create Date: 2026-06-22 10:37:33.521719
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7f9067c9bbe'
down_revision: Union[str, None] = '8a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hazard_reports',
        sa.Column('rectification_reply', sa.Text(), nullable=True, comment='整改回复内容'),
        schema='safety')


def downgrade() -> None:
    op.drop_column('hazard_reports', 'rectification_reply', schema='safety')
