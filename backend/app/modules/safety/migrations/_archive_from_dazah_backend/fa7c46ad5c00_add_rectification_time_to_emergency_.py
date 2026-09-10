"""add_rectification_time_to_emergency_drill_records

Revision ID: fa7c46ad5c00
Revises: 3f9a7c1b5d2f
Create Date: 2026-08-06 12:19:43.244578
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fa7c46ad5c00'
down_revision: Union[str, None] = '3f9a7c1b5d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅本次需求：演练统计表新增「整改时间」列
    op.add_column(
        'emergency_drill_records',
        sa.Column('rectification_time', sa.Date(), nullable=True, comment='整改时间'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('emergency_drill_records', 'rectification_time', schema='safety')
