"""merge main production heads and warehouse config

Revision ID: c7c4b6b6a8a4
Revises: aae52f0e112e, e5c4d8a91b72
Create Date: 2026-09-14 18:23:54.768247
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'c7c4b6b6a8a4'
down_revision: str | None = ('aae52f0e112e', 'e5c4d8a91b72')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
