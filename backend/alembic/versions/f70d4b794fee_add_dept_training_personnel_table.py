"""add dept_training_personnel table

Revision ID: f70d4b794fee
Revises: e6c93c255136
Create Date: 2026-06-30 15:35:30.754467
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'f70d4b794fee'
down_revision: str | None = 'e6c93c255136'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema, "table": table},
    ).first()
    return row is not None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    if _table_exists('dept_training_personnel', 'hr'):
        return
    op.create_table('dept_training_personnel',
        sa.Column('id', sa.Uuid(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('display_dept', sa.String(128), nullable=True),
        sa.Column('department', sa.String(128), nullable=True),
        sa.Column('admins', sa.Text(), nullable=True),
        sa.Column('dept_head', sa.Text(), nullable=True),
        sa.Column('primary_trainer', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false')),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_table('dept_training_personnel', schema='hr')
