"""production: node_field_values 增加 filled_at/filled_by 快照

Revision ID: 18cf6e77f5c0
Revises: 9883b0ea089b
Create Date: 2026-08-05 16:22:07.096295
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '18cf6e77f5c0'
down_revision: Union[str, None] = '9883b0ea089b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'node_field_values',
        sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True, comment='当前值最后填写时间(含补录)'),
        schema='production',
    )
    op.add_column(
        'node_field_values',
        sa.Column('filled_by', sa.Uuid(), nullable=True, comment='当前值最后填写人(含补录)'),
        schema='production',
    )
    op.create_foreign_key(
        op.f('node_field_values_filled_by_fkey'),
        'node_field_values',
        'users',
        ['filled_by'],
        ['id'],
        source_schema='production',
        referent_schema='identity',
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('node_field_values_filled_by_fkey'),
        'node_field_values',
        schema='production',
        type_='foreignkey',
    )
    op.drop_column('node_field_values', 'filled_by', schema='production')
    op.drop_column('node_field_values', 'filled_at', schema='production')
