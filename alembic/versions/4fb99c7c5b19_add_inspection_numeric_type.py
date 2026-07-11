"""add inspection numeric type

Revision ID: 4fb99c7c5b19
Revises: 7419e6f7039e
Create Date: 2026-07-10 11:51:17.752478
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4fb99c7c5b19'
down_revision: Union[str, None] = '7419e6f7039e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'inspection_template_items',
        sa.Column(
            'data_type',
            sa.String(length=10),
            server_default='text',
            nullable=False,
            comment='数据类型：text/numeric',
        ),
        schema='equipment',
    )
    op.add_column(
        'inspection_template_items',
        sa.Column(
            'unit',
            sa.String(length=20),
            nullable=True,
            comment='单位（仅 numeric 有意义），如 ℃/MPa/A',
        ),
        schema='equipment',
    )
    op.add_column(
        'inspection_records',
        sa.Column(
            'numeric_value',
            sa.Numeric(),
            nullable=True,
            comment='数值型检查项解析后的实测值',
        ),
        schema='equipment',
    )


def downgrade() -> None:
    op.drop_column('inspection_records', 'numeric_value', schema='equipment')
    op.drop_column('inspection_template_items', 'unit', schema='equipment')
    op.drop_column('inspection_template_items', 'data_type', schema='equipment')
