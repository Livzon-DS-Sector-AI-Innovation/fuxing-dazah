"""merge heads quality/main

Revision ID: 600b219843ca
Revises: 286c8ec29dd9, 5c210862ae7c
Create Date: 2026-09-11 12:05:05.730050
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '600b219843ca'
down_revision: Union[str, None] = ('286c8ec29dd9', '5c210862ae7c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
