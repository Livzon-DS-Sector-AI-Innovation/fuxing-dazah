"""merge local qa-coa-copylinks and hr-offboarding (#64) chains

Revision ID: 58152f3280b2
Revises: b8d2e6a4c1f3, eb6a6a5d40b1
Create Date: 2026-11-27 10:52:47.499085
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58152f3280b2'
down_revision: Union[str, None] = ('b8d2e6a4c1f3', 'eb6a6a5d40b1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
