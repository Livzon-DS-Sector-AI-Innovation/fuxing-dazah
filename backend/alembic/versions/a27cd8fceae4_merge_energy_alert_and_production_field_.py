"""merge energy alert and production field fixes

Revision ID: a27cd8fceae4
Revises: 18cf6e77f5c0, f4a59df9f07f
Create Date: 2026-08-06 11:14:17.716118
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a27cd8fceae4'
down_revision: Union[str, None] = ('18cf6e77f5c0', 'f4a59df9f07f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
