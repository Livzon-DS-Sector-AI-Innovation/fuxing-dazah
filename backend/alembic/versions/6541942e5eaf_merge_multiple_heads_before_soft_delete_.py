"""merge multiple heads before soft-delete-unique-index migration

Revision ID: 6541942e5eaf
Revises: 449b1347ab8a, 706fdf53f046, baaa69a19144
Create Date: 2026-06-23 20:50:52.925466
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6541942e5eaf'
down_revision: Union[str, None] = ('449b1347ab8a', '706fdf53f046', 'baaa69a19144')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
