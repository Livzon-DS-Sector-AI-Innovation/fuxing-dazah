"""merge heads

Revision ID: e22654fa1b3c
Revises: 6917a7dadfe6, a3b4c5d6e7f8
Create Date: 2026-07-07 08:34:27.154305
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e22654fa1b3c'
down_revision: Union[str, None] = ('6917a7dadfe6', 'a3b4c5d6e7f8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
