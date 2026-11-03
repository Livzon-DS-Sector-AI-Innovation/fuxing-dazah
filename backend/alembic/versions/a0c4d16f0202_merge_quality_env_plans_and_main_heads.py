"""merge quality env plans and main heads

Revision ID: a0c4d16f0202
Revises: a4c1f27b9e03, aed7833e8cfb
Create Date: 2026-11-03 15:24:36.550410
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0c4d16f0202'
down_revision: Union[str, None] = ('a4c1f27b9e03', 'aed7833e8cfb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
