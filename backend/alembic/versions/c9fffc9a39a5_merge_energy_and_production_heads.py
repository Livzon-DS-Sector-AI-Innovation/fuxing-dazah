"""merge energy and production heads

Revision ID: c9fffc9a39a5
Revises: 63a79de496da, 660eaaf6349b
Create Date: 2026-07-22 10:29:49.991185
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9fffc9a39a5'
down_revision: Union[str, None] = ('63a79de496da', '660eaaf6349b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
