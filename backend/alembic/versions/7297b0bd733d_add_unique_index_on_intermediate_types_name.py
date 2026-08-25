"""add unique index on intermediate_types name

Revision ID: 7297b0bd733d
Revises: a61e0b08bcb6
Create Date: 2026-08-12 11:29:14.241280
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '7297b0bd733d'
down_revision: Union[str, None] = 'a61e0b08bcb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_production_intermediate_types_name',
        'intermediate_types',
        ['name'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_production_intermediate_types_name',
        table_name='intermediate_types',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
