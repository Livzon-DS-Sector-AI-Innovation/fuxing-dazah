"""merge energy yhb fixes with main

Revision ID: 43c7be42cd78
Revises: 0fb346de3256, d0370703ae72
Create Date: 2026-08-10 11:18:58.225910
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43c7be42cd78'
down_revision: Union[str, None] = ('0fb346de3256', 'd0370703ae72')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
