"""merge heads quality/main 0914

Revision ID: 411c172d18a3
Revises: 9aa36d488a32, aae52f0e112e
Create Date: 2026-09-14 11:33:09.801782
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '411c172d18a3'
down_revision: Union[str, None] = ('9aa36d488a32', 'aae52f0e112e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
