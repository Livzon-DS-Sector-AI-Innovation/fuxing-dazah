"""merge upstream

Revision ID: f2a8b17621ab
Revises: 623e993e6c32, c9fffc9a39a5
Create Date: 2026-07-22 17:14:44.347349
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a8b17621ab'
down_revision: Union[str, None] = ('623e993e6c32', 'c9fffc9a39a5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
