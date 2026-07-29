"""merge heads

Revision ID: 12e74fca567d
Revises: 3b8ddf96914a, 43358e02707c
Create Date: 2026-07-23 18:39:38.794833
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12e74fca567d'
down_revision: Union[str, None] = ('3b8ddf96914a', '43358e02707c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
