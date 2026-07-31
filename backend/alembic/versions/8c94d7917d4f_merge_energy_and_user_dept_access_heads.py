"""merge_energy_and_user_dept_access_heads

Revision ID: 8c94d7917d4f
Revises: 393e668958f2, 3cb53e7c4a68
Create Date: 2026-07-31 10:40:32.250247
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c94d7917d4f'
down_revision: Union[str, None] = ('393e668958f2', '3cb53e7c4a68')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
