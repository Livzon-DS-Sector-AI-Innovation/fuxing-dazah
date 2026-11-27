"""merge hr-headcount chain (#58) and local qa-coa/role-group chain

Revision ID: 389529687153
Revises: 38854a399971, c4e9a2f83b17
Create Date: 2026-11-16 17:34:57.690035
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '389529687153'
down_revision: str | None = ('38854a399971', 'c4e9a2f83b17')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
