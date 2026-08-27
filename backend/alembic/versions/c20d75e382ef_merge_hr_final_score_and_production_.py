"""merge hr final_score and production line product links

Revision ID: c20d75e382ef
Revises: 6422239f947c, 7bf1a1f4aa16
Create Date: 2026-08-27 18:17:09.220484
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c20d75e382ef'
down_revision: Union[str, None] = ('6422239f947c', '7bf1a1f4aa16')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
