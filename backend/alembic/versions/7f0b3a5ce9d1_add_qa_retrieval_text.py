"""add normalized retrieval text to QA evidence and chunks.

Raw ``content`` remains the immutable parser output used for evidence and
citations.  The nullable columns added here are populated for new extraction
runs; legacy rows continue to be readable through the application fallback to
``content``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f0b3a5ce9d1"
down_revision: str | None = "43f0e1e69679"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_text_segments",
        sa.Column(
            "retrieval_text",
            sa.Text(),
            nullable=True,
            comment="去除版式标记后的检索文本；legacy 数据为空时回退 content",
        ),
        schema="qa",
    )
    op.add_column(
        "document_text_segments",
        sa.Column(
            "retrieval_text_hash",
            sa.String(64),
            nullable=True,
            comment="检索文本 SHA-256（规范化版本）",
        ),
        schema="qa",
    )
    op.add_column(
        "document_text_chunks",
        sa.Column(
            "retrieval_text",
            sa.Text(),
            nullable=True,
            comment="去除版式标记后的检索文本；legacy 数据为空时回退 content",
        ),
        schema="qa",
    )
    op.add_column(
        "document_text_chunks",
        sa.Column(
            "retrieval_text_hash",
            sa.String(64),
            nullable=True,
            comment="检索文本 SHA-256（规范化版本）",
        ),
        schema="qa",
    )
    op.add_column(
        "document_text_chunks",
        sa.Column(
            "retrieval_char_count",
            sa.Integer(),
            nullable=True,
            comment="检索文本字符数；legacy 数据为空",
        ),
        schema="qa",
    )
    op.add_column(
        "document_text_chunks",
        sa.Column(
            "retrieval_token_count",
            sa.Integer(),
            nullable=True,
            comment="检索文本 token 估算；legacy 数据为空",
        ),
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_segments_retrieval_hash",
        "document_text_segments",
        ["retrieval_text_hash"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_segments_retrieval_trgm",
        "document_text_segments",
        ["retrieval_text"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"retrieval_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_qa_document_text_chunks_retrieval_hash",
        "document_text_chunks",
        ["retrieval_text_hash"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_chunks_retrieval_trgm",
        "document_text_chunks",
        ["retrieval_text"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"retrieval_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qa_document_text_chunks_retrieval_trgm",
        table_name="document_text_chunks",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_chunks_retrieval_hash",
        table_name="document_text_chunks",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_segments_retrieval_trgm",
        table_name="document_text_segments",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_segments_retrieval_hash",
        table_name="document_text_segments",
        schema="qa",
    )
    for name in (
        "retrieval_token_count",
        "retrieval_char_count",
        "retrieval_text_hash",
        "retrieval_text",
    ):
        op.drop_column(name=name, table_name="document_text_chunks", schema="qa")
    for name in ("retrieval_text_hash", "retrieval_text"):
        op.drop_column(name=name, table_name="document_text_segments", schema="qa")
