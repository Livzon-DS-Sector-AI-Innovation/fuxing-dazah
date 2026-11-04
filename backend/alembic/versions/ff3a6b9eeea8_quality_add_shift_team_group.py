"""quality add shift team group

Revision ID: ff3a6b9eeea8
Revises: eb083fd428c6
Create Date: 2026-10-29 09:30:28.835836
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ff3a6b9eeea8'
down_revision: str | None = 'eb083fd428c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 班组归属组别（仪器组/生物组/理化组，互相独立轮换）
    op.add_column(
        "quality_shift_teams",
        sa.Column("group_key", sa.String(length=32), server_default="仪器组", nullable=False,
                  comment="班组归属组别（仪器组/生物组/理化组）"),
        schema="quality",
    )


def downgrade() -> None:
    op.drop_column("quality_shift_teams", "group_key", schema="quality")
