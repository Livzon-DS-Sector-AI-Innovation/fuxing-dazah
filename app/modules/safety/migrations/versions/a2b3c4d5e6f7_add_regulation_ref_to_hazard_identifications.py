"""add regulation_id and regulation_name to hazard_identifications

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-25

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: str | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": schema, "table": table, "column": column},
    ).first()
    return row is not None


def _add_column_if_missing(table: str, column: sa.Column, *, schema: str) -> None:
    if not _column_exists(table, column.name, schema):
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    _add_column_if_missing(
        'hazard_identifications',
        sa.Column('regulation_id', sa.Uuid(), nullable=True, comment='引用的安全操作规程 ID（替代附件上传）'),
        schema='safety',
    )
    _add_column_if_missing(
        'hazard_identifications',
        sa.Column('regulation_name', sa.String(255), nullable=True, comment='引用的安全操作规程名称'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('hazard_identifications', 'regulation_name', schema='safety')
    op.drop_column('hazard_identifications', 'regulation_id', schema='safety')
