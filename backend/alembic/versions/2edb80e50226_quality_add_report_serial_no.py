"""quality add report serial_no

Revision ID: 2edb80e50226
Revises: 4fc58ac5850d
Create Date: 2026-09-18 15:51:25.207802
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2edb80e50226'
down_revision: Union[str, None] = '4fc58ac5850d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'report_records',
        sa.Column('serial_no', sa.String(length=32), nullable=True, comment='流水号（年月日+当日序号，如 26091801）'),
        schema='quality',
    )


def downgrade() -> None:
    op.drop_column('report_records', 'serial_no', schema='quality')
