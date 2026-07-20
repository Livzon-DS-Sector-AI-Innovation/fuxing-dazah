"""add consumed_parts_data to work_orders

Revision ID: 9741f88ac586
Revises: 651178fee589
Create Date: 2026-07-20 19:49:00.295073
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9741f88ac586'
down_revision: Union[str, None] = '651178fee589'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'work_orders',
        sa.Column('consumed_parts_data', sa.Text(), nullable=True,
                  comment='提交完成时选择的消耗备件 JSON'),
        schema='equipment',
    )


def downgrade() -> None:
    op.drop_column('work_orders', 'consumed_parts_data', schema='equipment')
