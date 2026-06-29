"""add knowledge_card JSONB to knowledge_articles

Revision ID: e1k2m3n4o5p6
Revises: d121aec51082
Create Date: 2026-06-24 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'e1k2m3n4o5p6'
down_revision: Union[str, None] = 'd121aec51082'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "knowledge_card",
            JSONB,
            nullable=True,
            comment="AI 知识卡片 JSON（结构化法规摘要，供 AI 识别注入 prompt）"
        ),
        schema="safety",
    )
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "card_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="知识卡片生成时间"
        ),
        schema="safety",
    )
    op.add_column(
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
