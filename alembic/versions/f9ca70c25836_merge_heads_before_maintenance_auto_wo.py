"""merge heads before maintenance auto-wo

Revision ID: f9ca70c25836
Revises: 20260615_0001_hr, f1a2b3c4d5e6
Create Date: 2026-06-15 16:09:44.491589
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9ca70c25836'
down_revision: Union[str, None] = ('20260615_0001_hr', 'f1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
