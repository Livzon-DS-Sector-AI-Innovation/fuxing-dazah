"""merge qa and hr heads

Revision ID: ff7e451f0f9c
Revises: 3ead528832f8, a3f7c1d9e5b2
Create Date: 2026-11-27 08:42:46.159446
"""

# revision identifiers, used by Alembic.
revision: str = 'ff7e451f0f9c'
down_revision: str | tuple[str, str] | None = ('3ead528832f8', 'a3f7c1d9e5b2')
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
