"""add feishu_shared_url to knowledge_articles

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-07-08 13:46:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h2i3j4k5l6m7"
down_revision: str | None = "g1h2i3j4k5l6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_articles",
        sa.Column(
            "feishu_shared_url",
            sa.String(1024),
            nullable=True,
            comment="飞书Bitable记录分享链接（/record/ 格式）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("knowledge_articles", "feishu_shared_url", schema="safety")
