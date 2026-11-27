"""merge quality and qa heads after main sync

Revision ID: fc1194b67aa7
Revises: 3187ab7fb5cd, 7f0b3a5ce9d1
Create Date: 2026-10-09 17:36:42.903879
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc1194b67aa7'
down_revision: Union[str, None] = ('3187ab7fb5cd', '7f0b3a5ce9d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
