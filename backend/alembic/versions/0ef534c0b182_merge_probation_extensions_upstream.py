"""merge probation extensions upstream

Revision ID: 0ef534c0b182
Revises: 137c5228d679, 3cb8b3fa4e6d
Create Date: 2026-07-20 00:06:52.949229
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ef534c0b182'
down_revision: Union[str, None] = ('137c5228d679', '3cb8b3fa4e6d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
