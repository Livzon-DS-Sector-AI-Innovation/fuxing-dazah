"""merge planning enhancement heads

Revision ID: 7df079890c60
Revises: 4c4e2892ccaa, a1a29614b41e
Create Date: 2026-07-28 10:57:15.777553
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7df079890c60'
down_revision: Union[str, None] = ('4c4e2892ccaa', 'a1a29614b41e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
