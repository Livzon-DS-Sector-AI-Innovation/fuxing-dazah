"""quality rename test date to production date

Revision ID: 78c53d5ba9f4
Revises: 4973c32c5a76
Create Date: 2026-09-03 14:59:38.978539
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78c53d5ba9f4'
down_revision: Union[str, None] = '4973c32c5a76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.alter_column('quality_test_tasks', 'test_date',
                    new_column_name='production_date',
                    existing_type=sa.String(length=32), nullable=True,
                    schema='quality',
                    comment='生产日期（YYYY-MM-DD）')


def downgrade() -> None:
    op.alter_column('quality_test_tasks', 'production_date',
                    new_column_name='test_date',
                    existing_type=sa.String(length=32), nullable=True,
                    schema='quality',
                    comment='检验日期（YYYY-MM-DD）')
