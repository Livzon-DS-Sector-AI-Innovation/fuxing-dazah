"""rename plan_items product fields to intermediate_type

Revision ID: 43358e02707c
Revises: 3f5f8e594160
Create Date: 2026-07-23 14:35:04.272299
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '43358e02707c'
down_revision: Union[str, None] = '3f5f8e594160'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'plan_items',
        'product_id',
        new_column_name='intermediate_type_id',
        schema='production',
    )
    op.alter_column(
        'plan_items',
        'product_name',
        new_column_name='intermediate_type_name',
        schema='production',
    )


def downgrade() -> None:
    op.alter_column(
        'plan_items',
        'intermediate_type_id',
        new_column_name='product_id',
        schema='production',
    )
    op.alter_column(
        'plan_items',
        'intermediate_type_name',
        new_column_name='product_name',
        schema='production',
    )
