"""merge hr certificates and qa heads

Revision ID: dada00079c92
Revises: 7a603109281d, e13da4b58fbd
Create Date: 2026-11-24 14:37:16.690211
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dada00079c92'
down_revision: Union[str, None] = ('7a603109281d', 'e13da4b58fbd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
