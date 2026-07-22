"""merge 3090d84bc3fe and f70d4b794fee

Revision ID: c637e4490bab
Revises: 3090d84bc3fe, f70d4b794fee
Create Date: 2026-06-30 18:15:54.459271
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c637e4490bab'
down_revision: Union[str, None] = ('3090d84bc3fe', 'f70d4b794fee')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
