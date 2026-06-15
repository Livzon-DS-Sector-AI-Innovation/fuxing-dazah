"""merge scheduled_tasks and maintenance branches

Revision ID: abdaf2f5b61f
Revises: 20260615_0001, f81e0b223a81
Create Date: 2026-06-15 18:27:49.357877
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abdaf2f5b61f'
down_revision: Union[str, None] = ('20260615_0001', 'f81e0b223a81')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
