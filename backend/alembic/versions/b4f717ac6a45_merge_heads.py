"""merge heads

Revision ID: b4f717ac6a45
Revises: 12e74fca567d, cc1aba4571c9
Create Date: 2026-07-23 21:05:52.067215
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f717ac6a45'
down_revision: Union[str, None] = ('12e74fca567d', 'cc1aba4571c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
