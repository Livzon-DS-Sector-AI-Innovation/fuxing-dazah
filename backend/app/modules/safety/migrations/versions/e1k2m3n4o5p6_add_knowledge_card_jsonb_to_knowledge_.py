"""add knowledge_card JSONB to knowledge_articles

Revision ID: e1k2m3n4o5p6
Revises: d121aec51082
Create Date: 2026-06-24 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e1k2m3n4o5p6'
down_revision: str | None = 'd121aec51082'
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
        "knowledge_articles",
        sa.Column(
            "knowledge_card",
            JSONB,
            nullable=True,
            comment="AI 知识卡片 JSON（结构化法规摘要，供 AI 识别注入 prompt）"
        ),
        schema="safety",
    )
    _add_column_if_missing(
        "knowledge_articles",
        sa.Column(
            "card_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="知识卡片生成时间"
        ),
        schema="safety",
    )
    _add_column_if_missing(
        "knowledge_articles",
        sa.Column(
            "card_version",
            sa.Integer,
            nullable=False,
            server_default="1",
            comment="知识卡片版本号"
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("knowledge_articles", "card_version", schema="safety")
    op.drop_column("knowledge_articles", "card_generated_at", schema="safety")
    op.drop_column("knowledge_articles", "knowledge_card", schema="safety")
