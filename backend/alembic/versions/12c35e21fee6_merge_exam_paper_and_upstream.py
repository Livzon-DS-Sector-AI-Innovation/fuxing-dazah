"""merge exam paper and upstream

Revision ID: 12c35e21fee6
Revises: 79ae97a9950f, fefe16a31b9d
Create Date: 2026-07-17 14:09:29.800057
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12c35e21fee6'
down_revision: Union[str, None] = ('79ae97a9950f', 'fefe16a31b9d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
