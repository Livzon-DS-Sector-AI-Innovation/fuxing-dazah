"""merge equipment inspection_route_schedules head

Revision ID: 241f68a331ab
Revises: 64bf781f2e81, 949d3efb8bf8
Create Date: 2026-06-24 09:29:19.238979
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '241f68a331ab'
down_revision: Union[str, None] = ('64bf781f2e81', '949d3efb8bf8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
