"""add_probation_fields_to_employee

Revision ID: 86ca84a3662e
Revises: d02196edd429
Create Date: 2026-07-17 15:07:13.077695
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '86ca84a3662e'
down_revision: Union[str, None] = 'd02196edd429'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('probation_end_date', sa.Date(), nullable=True, comment='试用期截止日'), schema='hr')
    op.add_column('employees', sa.Column('mentor_name', sa.String(length=64), nullable=True, comment='导师姓名'), schema='hr')
    op.add_column('employees', sa.Column('regularization_date', sa.Date(), nullable=True, comment='转正日期'), schema='hr')


def downgrade() -> None:
    op.drop_column('employees', 'regularization_date', schema='hr')
    op.drop_column('employees', 'mentor_name', schema='hr')
    op.drop_column('employees', 'probation_end_date', schema='hr')
