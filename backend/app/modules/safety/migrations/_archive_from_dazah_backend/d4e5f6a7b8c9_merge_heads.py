"""merge regulation_chunks head with global head

Revision ID: d4e5f6a7b8c9
Revises: e22654fa1b3c, c1d2e3f4a5b6
Create Date: 2026-07-07 11:05:00.000000
"""
from collections.abc import Sequence

# revision identifiers
revision: str = 'd4e5f6a7b8c9'
down_revision: str | tuple[str, ...] | None = ('e22654fa1b3c', 'c1d2e3f4a5b6')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
