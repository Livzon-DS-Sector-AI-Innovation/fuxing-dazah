"""merge energy and safety heads

Revision ID: 77f1c0c605ba
Revises: 1fa57660ca98, 3fbb2904cf43
Create Date: 2026-06-08 09:54:21.820927
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77f1c0c605ba'
down_revision: Union[str, None] = ('1fa57660ca98', '3fbb2904cf43')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
