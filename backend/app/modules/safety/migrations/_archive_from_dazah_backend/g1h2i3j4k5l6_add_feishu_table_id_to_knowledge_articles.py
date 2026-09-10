"""add feishu_table_id to knowledge_articles

Revision ID: g1h2i3j4k5l6
Revises: 3f9cf282578f
Create Date: 2026-07-08 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g1h2i3j4k5l6"
down_revision: str | None = "3f9cf282578f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_articles",
        sa.Column("feishu_table_id", sa.String(64), nullable=True, comment="飞书Bitable数据表ID"),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("knowledge_articles", "feishu_table_id", schema="safety")
