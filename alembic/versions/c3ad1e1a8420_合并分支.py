"""合并分支

Revision ID: c3ad1e1a8420
Revises: 3481d7ec2630, c637e4490bab
Create Date: 2026-07-01 08:45:48.765947
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3ad1e1a8420'
down_revision: Union[str, None] = ('3481d7ec2630', 'c637e4490bab')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
