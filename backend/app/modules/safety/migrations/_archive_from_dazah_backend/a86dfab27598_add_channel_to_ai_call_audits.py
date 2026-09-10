"""add channel to ai_call_audits

Revision ID: a86dfab27598
Revises: 1cfaa7a07a06
Create Date: 2026-07-15 15:55:13.969587
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a86dfab27598'
down_revision: Union[str, None] = '1cfaa7a07a06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_call_audits",
        sa.Column(
            "channel",
            sa.String(length=16),
            nullable=True,
            comment="调用渠道：web / feishu / system",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("ai_call_audits", "channel", schema="safety")
