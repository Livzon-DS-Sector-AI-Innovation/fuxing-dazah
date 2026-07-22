"""merge 2af364a150a5 and aa86215f21ed

Revision ID: a09acdc0169c
Revises: 2af364a150a5, aa86215f21ed
Create Date: 2026-06-29 20:08:38.894894
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a09acdc0169c'
down_revision: Union[str, None] = ('2af364a150a5', 'aa86215f21ed')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
