"""quality inspection plan notified_at

Revision ID: 08660e45bc88
Revises: ff3a6b9eeea8
Create Date: 2026-10-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08660e45bc88'
down_revision: Union[str, None] = 'ff3a6b9eeea8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_inspection_plans', sa.Column('notified_at', sa.String(length=32), nullable=True, comment='排班通知最近下发时间 YYYY-MM-DD HH:mm（排班变更后清空）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_inspection_plans', 'notified_at', schema='quality')
