"""merge heads after main sync

Revision ID: b0262fe5b80f
Revises: ba2d4134a5a2, fde16f392af2
Create Date: 2026-09-24 11:39:11.877234
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0262fe5b80f'
down_revision: Union[str, None] = ('ba2d4134a5a2', 'fde16f392af2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
