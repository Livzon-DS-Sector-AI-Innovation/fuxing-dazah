"""merge equipment dept_id and hr trainers heads

Revision ID: ec7e0e3b9953
Revises: 0fac3372e248, aa86215f21ed
Create Date: 2026-06-29 19:42:29.848096
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec7e0e3b9953'
down_revision: Union[str, None] = ('0fac3372e248', 'aa86215f21ed')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
