"""merge 284c3b08d3dc and 80dbc811b69b

Revision ID: 3090d84bc3fe
Revises: 284c3b08d3dc, 80dbc811b69b
Create Date: 2026-06-30 15:33:59.153819
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3090d84bc3fe'
down_revision: Union[str, None] = ('284c3b08d3dc', '80dbc811b69b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
