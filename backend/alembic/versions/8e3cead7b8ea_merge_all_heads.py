"""merge all heads

Revision ID: 8e3cead7b8ea
Revises: 449b1347ab8a, 706fdf53f046, baaa69a19144
Create Date: 2026-06-29 10:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '8e3cead7b8ea'
down_revision: Union[str, None] = ('449b1347ab8a', '706fdf53f046', 'baaa69a19144')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
