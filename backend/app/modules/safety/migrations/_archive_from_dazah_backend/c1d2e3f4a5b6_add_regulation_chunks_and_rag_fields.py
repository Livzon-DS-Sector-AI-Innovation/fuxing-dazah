"""add regulation_chunks table and rag fields to knowledge_articles

Revision ID: c1d2e3f4a5b6
Revises: baaa69a19144
Create Date: 2026-07-07 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = 'c1d2e3f4a5b6'
down_revision: str | None = 'a3b4c5d6e7f8'
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

    # ═══ 1. Add RAG fields to knowledge_articles ═══
    table = "knowledge_articles"
    _add_column_if_missing(
        table,
        sa.Column("full_text", sa.Text, nullable=True, comment="完整解析文本（供分块使用）"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column("full_text_hash", sa.String(64), nullable=True, comment="全文 SHA256 哈希（增量检测）"),
        schema=schema,
    )
    _add_column_if_missing(
        table,
        sa.Column(
            "chunk_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="分块数量",
        ),
        schema=schema,
    )

    # ═══ 2. Create regulation_chunks table ═══
    if not _table_exists("regulation_chunks", schema):
        op.create_table(
            "regulation_chunks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("article_id", UUID(as_uuid=True),
                      sa.ForeignKey("safety.knowledge_articles.id"), nullable=False,
                      comment="所属法规文档 ID"),
            sa.Column("chunk_text", sa.Text, nullable=False, comment="条款原文"),
            sa.Column("chunk_index", sa.Integer, nullable=False, comment="在文档中的序号"),
            sa.Column("doc_title", sa.String(500), nullable=False, comment="文档标题"),
            sa.Column("doc_category", sa.String(100), nullable=True, comment="文档类别"),
            sa.Column("chapter_title", sa.String(500), nullable=True, comment="章节标题"),
            sa.Column("article_ref", sa.String(100), nullable=True, comment="条款编号"),
            sa.Column("embedding", sa.Text, nullable=True, comment="向量嵌入（JSON 数组字符串）"),
            sa.Column("priority", sa.String(2), nullable=False, server_default="P2",
                      comment="优先级"),
            sa.Column("cites_chunk_ids", sa.JSON, nullable=True, comment="引用的其他 chunk ID"),
            sa.Column("cited_by_chunk_ids", sa.JSON, nullable=True, comment="被其他 chunk 引用"),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("created_by", UUID(as_uuid=True),
                      sa.ForeignKey("identity.users.id"), nullable=True),
            sa.Column("updated_by", UUID(as_uuid=True),
                      sa.ForeignKey("identity.users.id"), nullable=True),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            schema=schema,
        )

        # Indexes
        op.create_index("ix_regulation_chunks_article_id", "regulation_chunks",
                        ["article_id"], schema=schema)
        op.create_index("ix_regulation_chunks_chunk_index", "regulation_chunks",
                        ["article_id", "chunk_index"], schema=schema)
        op.create_index("ix_regulation_chunks_doc_category", "regulation_chunks",
                        ["doc_category"], schema=schema)
        op.create_index("ix_regulation_chunks_priority", "regulation_chunks",
                        ["priority"], schema=schema)

    # ═══ 3. pgvector extension (skipped — embedding stored as JSON text) ═══
    # When pgvector becomes available, run:
    #   CREATE EXTENSION IF NOT EXISTS vector;
    # And add: embedding VECTOR(1024) column to regulation_chunks.


def downgrade() -> None:
    schema = "safety"

    # Drop regulation_chunks table
    op.execute(sa.text("DROP TABLE IF EXISTS safety.regulation_chunks CASCADE"))

    # Drop RAG fields from knowledge_articles
    for col in ("chunk_count", "full_text_hash", "full_text"):
        op.drop_column("knowledge_articles", col, schema=schema)
