"""add knowledge_card, card_generated_at, card_version to knowledge_articles

Revision ID: 5929fcca8939
Revises: b2c3d4e5f6a7
Create Date: 2026-07-03 09:24:12.858679
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5929fcca8939'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str, schema: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :col"
        ),
        {"schema": schema, "table": table, "col": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    if not _column_exists(table, "knowledge_card", schema):
        op.add_column(table, sa.Column("knowledge_card", sa.JSON(), nullable=True, comment="知识卡片JSON"), schema=schema)
    if not _column_exists(table, "card_generated_at", schema):
        op.add_column(table, sa.Column("card_generated_at", sa.DateTime(timezone=True), nullable=True, comment="卡片生成时间"), schema=schema)
    if not _column_exists(table, "card_version", schema):
        op.add_column(table, sa.Column("card_version", sa.Integer(), server_default="1", nullable=False, comment="知识卡片版本号"), schema=schema)


def downgrade() -> None:
    schema = "safety"
    table = "knowledge_articles"

    for col in ("knowledge_card", "card_generated_at", "card_version"):
        if _column_exists(table, col, schema):
            op.drop_column(table, col, schema=schema)
