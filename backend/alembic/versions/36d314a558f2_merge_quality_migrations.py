"""merge quality migrations

Revision ID: 36d314a558f2
Revises: 7df079890c60, c9d2f8a3e5b1
Create Date: 2026-07-29 11:38:52.744505
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36d314a558f2'
down_revision: Union[str, None] = ('7df079890c60', 'c9d2f8a3e5b1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
