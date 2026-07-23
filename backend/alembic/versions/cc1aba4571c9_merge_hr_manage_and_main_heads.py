"""merge hr_manage and main heads

Revision ID: cc1aba4571c9
Revises: 3b8ddf96914a, 3e06f949dca6
Create Date: 2026-07-23 19:59:19.622658
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc1aba4571c9'
down_revision: Union[str, None] = ('3b8ddf96914a', '3e06f949dca6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
