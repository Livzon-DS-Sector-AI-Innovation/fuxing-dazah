"""merge heads

Revision ID: c3e4ebb6a363
Revises: 17fda41cfdd0, 31d188858073
Create Date: 2026-07-13 11:30:23.652675
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e4ebb6a363'
down_revision: Union[str, None] = ('17fda41cfdd0', '31d188858073')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
