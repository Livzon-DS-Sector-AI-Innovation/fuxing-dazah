"""merge energy feature with main

Revision ID: e00e006eea52
Revises: 7df079890c60, bfc761e65724
Create Date: 2026-07-29 10:23:19.985477
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e00e006eea52'
down_revision: Union[str, None] = ('7df079890c60', 'bfc761e65724')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
