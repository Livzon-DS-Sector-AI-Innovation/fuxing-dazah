"""hr_departure_employee_category

离职台账补「员工性质」列（看板按用工性质月度离职分组维度）

Revision ID: c4e9a2f83b17
Revises: e8d2b4f71c96
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e9a2f83b17'
down_revision: Union[str, None] = 'e8d2b4f71c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'departure_records',
        sa.Column('employee_category', sa.String(64), nullable=True,
                  comment='员工性质（转正员工/退休返聘等；看板按用工性质月度离职分组用）'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('departure_records', 'employee_category', schema='hr')
