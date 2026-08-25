"""merge main toolbox and title review

Revision ID: 39c34ac3a668
Revises: 68c8572fc824, a1fa71ecd73d
Create Date: 2026-08-25 18:18:29.773088
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '39c34ac3a668'
down_revision: str | None = ('68c8572fc824', 'a1fa71ecd73d')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
