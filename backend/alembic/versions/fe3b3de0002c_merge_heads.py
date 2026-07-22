"""merge heads

Revision ID: fe3b3de0002c
Revises: 55b6248f4aee, b90d12802baf, c3ad1e1a8420
Create Date: 2026-07-03 15:16:43.521774
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe3b3de0002c'
down_revision: Union[str, None] = ('55b6248f4aee', 'b90d12802baf', 'c3ad1e1a8420')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
