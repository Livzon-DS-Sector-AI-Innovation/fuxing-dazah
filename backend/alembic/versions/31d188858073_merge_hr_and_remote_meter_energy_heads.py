"""merge hr and remote meter/energy heads

Revision ID: 31d188858073
Revises: 16fda41cfdd9, 7419e6f7039e
Create Date: 2026-07-10 15:55:30.432478
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31d188858073'
down_revision: Union[str, None] = ('16fda41cfdd9', '7419e6f7039e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
