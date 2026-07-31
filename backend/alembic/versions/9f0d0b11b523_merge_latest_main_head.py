"""merge_latest_main_head

Revision ID: 9f0d0b11b523
Revises: 0416a0f10a33, 8c94d7917d4f
Create Date: 2026-07-31 14:40:15.167671
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f0d0b11b523'
down_revision: Union[str, None] = ('0416a0f10a33', '8c94d7917d4f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
