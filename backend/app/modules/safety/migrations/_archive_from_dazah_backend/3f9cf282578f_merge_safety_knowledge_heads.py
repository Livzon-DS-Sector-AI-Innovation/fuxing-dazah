"""merge safety knowledge heads

Revision ID: 3f9cf282578f
Revises: a7b8c9d0e1f2, d4e5f6a7b8c9
Create Date: 2026-07-08 12:28:56.479654
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '3f9cf282578f'
down_revision: str | None = ('a7b8c9d0e1f2', 'd4e5f6a7b8c9')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
