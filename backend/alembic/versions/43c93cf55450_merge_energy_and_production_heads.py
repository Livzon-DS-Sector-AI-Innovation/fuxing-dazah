"""merge energy and production heads

Revision ID: 43c93cf55450
Revises: 393e668958f2, e01f2e3d4c5a
Create Date: 2026-07-30 17:51:38.519182
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43c93cf55450'
down_revision: Union[str, None] = ('393e668958f2', 'e01f2e3d4c5a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
