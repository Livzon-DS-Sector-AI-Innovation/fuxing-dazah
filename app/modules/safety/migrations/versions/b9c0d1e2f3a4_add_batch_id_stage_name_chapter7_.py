"""add batch_id, stage_name, chapter7_context to hazard_identifications

Revision ID: b9c0d1e2f3a4
Revises: a2b3c4d5e6f7
Create Date: 2026-06-26

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: str | None = 'a2b3c4d5e6f7'
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


def _index_exists(index_name: str, table: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = :schema AND tablename = :table AND indexname = :index"
        ),
        {"schema": schema, "table": table, "index": index_name},
    ).first()
    return row is not None


def upgrade() -> None:
    _add_column_if_missing(
        'hazard_identifications',
        sa.Column('batch_id', sa.Uuid(), nullable=True, comment='批次ID，同一regulation多工段同时创建时共享'),
        schema='safety',
    )
    _add_column_if_missing(
        'hazard_identifications',
        sa.Column('stage_name', sa.String(255), nullable=True, comment='工艺阶段名称（Chapter 7 H2 标题）'),
        schema='safety',
    )
    _add_column_if_missing(
        'hazard_identifications',
        sa.Column('chapter7_context', sa.Text(), nullable=True, comment='该工段对应的 Chapter 7 节选 Markdown（供Script 1使用）'),
        schema='safety',
    )
    if not _index_exists('ix_hazard_identifications_batch_id', 'hazard_identifications', 'safety'):
        op.create_index(
            'ix_hazard_identifications_batch_id',
            'hazard_identifications',
            ['batch_id'],
            schema='safety',
        )
    if not _index_exists('ix_hazard_identifications_regulation_batch', 'hazard_identifications', 'safety'):
        op.create_index(
            'ix_hazard_identifications_regulation_batch',
            'hazard_identifications',
            ['regulation_id', 'batch_id'],
            schema='safety',
        )


def downgrade() -> None:
    op.drop_index('ix_hazard_identifications_regulation_batch', table_name='hazard_identifications', schema='safety')
    op.drop_index('ix_hazard_identifications_batch_id', table_name='hazard_identifications', schema='safety')
    op.drop_column('hazard_identifications', 'chapter7_context', schema='safety')
    op.drop_column('hazard_identifications', 'stage_name', schema='safety')
    op.drop_column('hazard_identifications', 'batch_id', schema='safety')
