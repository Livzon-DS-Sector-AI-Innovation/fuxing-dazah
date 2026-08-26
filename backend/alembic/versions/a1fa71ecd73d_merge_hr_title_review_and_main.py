"""merge hr title review and main

Revision ID: a1fa71ecd73d
Revises: 7260d1dedfbf, a28b3a91f9b2
Create Date: 2026-08-25 17:37:32.698535
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'a1fa71ecd73d'
down_revision: str | None = ('7260d1dedfbf', 'a28b3a91f9b2')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
