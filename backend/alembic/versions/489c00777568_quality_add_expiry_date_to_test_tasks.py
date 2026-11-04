"""quality add expiry date to test tasks

Revision ID: 489c00777568
Revises: 78c53d5ba9f4
Create Date: 2026-09-03 15:01:17.374562
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '489c00777568'
down_revision: Union[str, None] = '78c53d5ba9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.add_column('quality_test_tasks',
                  sa.Column('expiry_date', sa.String(length=32), nullable=True,
                            comment='效期（生产日期+x年-1天，YYYY-MM-DD）'),
                  schema='quality')


def downgrade() -> None:
    op.drop_column('quality_test_tasks', 'expiry_date', schema='quality')
