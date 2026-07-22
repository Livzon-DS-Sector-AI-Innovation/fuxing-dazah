"""merge energy and meter heads

Revision ID: 624188c7eb3a
Revises: 159d4edfef7e, 9741f88ac586
Create Date: 2026-07-22 09:02:05.498573
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '624188c7eb3a'
down_revision: Union[str, None] = ('159d4edfef7e', '9741f88ac586')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
