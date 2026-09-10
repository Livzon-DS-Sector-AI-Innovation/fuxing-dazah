"""add cache tokens to ai_call_audits

Revision ID: dbd4fbaf6f41
Revises: e1b2375757dd
Create Date: 2026-07-16 08:56:57.973069
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dbd4fbaf6f41'
down_revision: Union[str, None] = 'e1b2375757dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_call_audits",
        sa.Column(
            "cache_hit_tokens",
            sa.Integer(),
            nullable=True,
            comment="DeepSeek prompt_cache_hit_tokens（前缀命中 token 数）",
        ),
        schema="safety",
    )
    op.add_column(
        "ai_call_audits",
        sa.Column(
            "cache_miss_tokens",
            sa.Integer(),
            nullable=True,
            comment="DeepSeek prompt_cache_miss_tokens（前缀未命中 token 数）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("ai_call_audits", "cache_hit_tokens", schema="safety")
    op.drop_column("ai_call_audits", "cache_miss_tokens", schema="safety")
