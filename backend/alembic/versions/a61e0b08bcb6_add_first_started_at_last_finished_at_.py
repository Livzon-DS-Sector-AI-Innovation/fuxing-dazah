"""add first_started_at and last_finished_at to batches

Revision ID: a61e0b08bcb6
Revises: 43c7be42cd78
Create Date: 2026-08-11 15:33:29.437057
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a61e0b08bcb6'
down_revision: Union[str, None] = '43c7be42cd78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'batches',
        sa.Column('first_started_at', sa.DateTime(timezone=True), nullable=True, comment='首工序开始时间'),
        schema='production',
    )
    op.add_column(
        'batches',
        sa.Column('last_finished_at', sa.DateTime(timezone=True), nullable=True, comment='末工序结束时间'),
        schema='production',
    )


def downgrade() -> None:
    op.drop_column('batches', 'last_finished_at', schema='production')
    op.drop_column('batches', 'first_started_at', schema='production')
