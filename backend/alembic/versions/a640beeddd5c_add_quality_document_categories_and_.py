"""add quality document_categories and standard_documents

Revision ID: a640beeddd5c
Revises: 4cb39e7a28c0
Create Date: 2026-09-01 14:59:13.177315
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a640beeddd5c'
down_revision: Union[str, None] = '4cb39e7a28c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")

    op.create_table(
        "document_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_name", sa.String(200), nullable=False, comment="产品名称"),
        sa.Column("category_name", sa.String(200), nullable=False, comment="大类名称"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        schema="quality",
    )
    op.create_index(
        "uq_quality_doc_cats",
        "document_categories",
        ["product_name", "category_name"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.create_table(
        "standard_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("category_id", sa.Uuid(), nullable=False, comment="所属大类，逻辑引用 quality.document_categories.id"),
        sa.Column("product_name", sa.String(200), nullable=False, comment="产品名称（冗余便于查询）"),
        sa.Column("original_filename", sa.String(500), nullable=False, comment="原始文件名"),
        sa.Column("file_path", sa.String(1000), nullable=False, comment="文件存储路径"),
        sa.Column("file_size", sa.Integer(), nullable=True, comment="文件大小（字节）"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        schema="quality",
    )
    op.create_index(
        "ix_quality_std_docs_cat",
        "standard_documents",
        ["category_id"],
        schema="quality",
    )
    op.create_index(
        "uq_quality_std_docs_file",
        "standard_documents",
        ["category_id", "original_filename"],
        unique=True,
        schema="quality",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_table("standard_documents", schema="quality")
    op.drop_table("document_categories", schema="quality")
