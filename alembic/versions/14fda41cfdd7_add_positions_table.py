"""add positions table

Revision ID: 14fda41cfdd7
Revises: c259c81b2e9c
Create Date: 2026-07-09 19:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '14fda41cfdd7'
down_revision: Union[str, None] = 'c259c81b2e9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.positions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            department VARCHAR(128) NOT NULL,
            name VARCHAR(128) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by UUID,
            updated_by UUID,
            is_deleted BOOLEAN NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_positions_department ON hr.positions (department)")


def downgrade() -> None:
    op.drop_table('positions', schema='hr')
