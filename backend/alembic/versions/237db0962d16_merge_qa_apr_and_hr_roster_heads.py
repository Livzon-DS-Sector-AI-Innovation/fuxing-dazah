"""merge qa-apr and hr-roster heads

Revision ID: 237db0962d16
Revises: a1f2c3d4e5f6, edc9dcd8f69e
Create Date: 2026-11-10 17:41:26.662415
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '237db0962d16'
down_revision: Union[str, None] = ('a1f2c3d4e5f6', 'edc9dcd8f69e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
