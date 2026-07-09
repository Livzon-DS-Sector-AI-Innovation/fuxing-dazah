"""merge 3 heads

Revision ID: 425cd778d104
Revises: 7419e6f7039e, 9f07a63b6eb4, h2i3j4k5l6m7
Create Date: 2026-07-09 19:22:11.927899
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '425cd778d104'
down_revision: Union[str, None] = ('7419e6f7039e', '9f07a63b6eb4', 'h2i3j4k5l6m7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
