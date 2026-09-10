"""add feishu_record_id and implementation_date to knowledge_articles

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-02 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
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


def _index_exists(table: str, index: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = :schema AND tablename = :table AND indexname = :index"
        ),
        {"schema": schema, "table": table, "index": index},
    ).first()
    return row is not None


def _add_column_if_missing(table: str, column: sa.Column, *, schema: str) -> None:
    if not _column_exists(table, column.name, schema):
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    _add_column_if_missing(
        table,
        sa.Column(
            "feishu_record_id",
            sa.String(128),
            nullable=True,
            comment="飞书多维表格记录ID，用于同步匹配",
        ),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column(
            "implementation_date",
            sa.Date,
            nullable=True,
            comment="法规实施日期",
        ),
        schema=schema,
    )

    # Index on feishu_record_id for fast lookup
    if not _index_exists(table, "ix_knowledge_articles_feishu_record_id", schema):
        op.create_index(
            "ix_knowledge_articles_feishu_record_id",
            table,
            ["feishu_record_id"],
            schema=schema,
        )

    # Partial unique index on feishu_record_id (only for non-deleted rows)
    if not _index_exists(table, "uq_knowledge_articles_feishu_record_id", schema):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_knowledge_articles_feishu_record_id "
                "ON safety.knowledge_articles (feishu_record_id) "
                "WHERE is_deleted = false"
            )
        )


def downgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    op.execute(sa.text("DROP INDEX IF EXISTS safety.uq_knowledge_articles_feishu_record_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS safety.ix_knowledge_articles_feishu_record_id"))
    op.drop_column(table, "feishu_record_id", schema=schema)
    op.drop_column(table, "implementation_date", schema=schema)
