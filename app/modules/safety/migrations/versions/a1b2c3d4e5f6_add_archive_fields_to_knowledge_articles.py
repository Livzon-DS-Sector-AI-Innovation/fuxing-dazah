"""add archive fields to knowledge_articles

Revision ID: a1b2c3d4e5f6
Revises: 9f07a63b6eb4
Create Date: 2026-07-02 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '9f07a63b6eb4'
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


def upgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    _add_column_if_missing(
        table,
        sa.Column("article_no", sa.String(64), nullable=True, comment="文档编号"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("source", sa.String(255), nullable=True, comment="来源/出处"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("author", sa.String(255), nullable=True, comment="作者/发布单位"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("publish_date", sa.Date, nullable=True, comment="发布日期"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("notes", sa.Text, nullable=True, comment="备注"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("version", sa.Integer, nullable=False, server_default="1", comment="版本号"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column(
            "superseded_by_id",
            UUID(as_uuid=True),
            nullable=True,
            comment="被替代为（指向新版本文档）",
        ),
        schema=schema,
    )

    # Partial unique index on article_no (only for non-deleted rows)
    if not _index_exists(table, "uq_knowledge_articles_article_no", schema):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_knowledge_articles_article_no "
                "ON safety.knowledge_articles (article_no) "
                "WHERE is_deleted = false"
            )
        )


def downgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    op.execute(sa.text("DROP INDEX IF EXISTS safety.uq_knowledge_articles_article_no"))
    op.drop_column(table, "superseded_by_id", schema=schema)
    op.drop_column(table, "version", schema=schema)
    op.drop_column(table, "notes", schema=schema)
    op.drop_column(table, "publish_date", schema=schema)
    op.drop_column(table, "author", schema=schema)
    op.drop_column(table, "source", schema=schema)
    op.drop_column(table, "article_no", schema=schema)
