"""merge all heads (meter + plan_change_logs + energy_user_dept)

Revision ID: 32c100f56e59
Revises: 0416a0f10a33, 1388bb526703, 8c94d7917d4f
Create Date: 2026-07-31 13:47:37.406830
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32c100f56e59'
down_revision: Union[str, None] = ('0416a0f10a33', '1388bb526703', '8c94d7917d4f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
