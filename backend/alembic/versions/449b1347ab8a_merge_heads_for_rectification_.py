"""merge heads for rectification_responsible_person

Revision ID: 449b1347ab8a
Revises: 3203f5f17333, f7f9067c9bbe
Create Date: 2026-06-22 17:33:12.107189
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '449b1347ab8a'
down_revision: Union[str, None] = ('3203f5f17333', 'f7f9067c9bbe')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
