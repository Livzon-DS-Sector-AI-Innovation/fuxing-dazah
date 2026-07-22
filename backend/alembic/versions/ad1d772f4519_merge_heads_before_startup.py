"""merge heads before startup

Revision ID: ad1d772f4519
Revises: e22654fa1b3c, e76ca014a4dd
Create Date: 2026-07-08 15:33:00.315871
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad1d772f4519'
down_revision: Union[str, None] = ('e22654fa1b3c', 'e76ca014a4dd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
