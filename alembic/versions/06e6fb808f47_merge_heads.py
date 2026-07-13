"""merge heads

Revision ID: 06e6fb808f47
Revises: 18fda41cfdd1, e5225e97aa98
Create Date: 2026-07-13 19:43:45.693984
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06e6fb808f47'
down_revision: Union[str, None] = ('18fda41cfdd1', 'e5225e97aa98')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
