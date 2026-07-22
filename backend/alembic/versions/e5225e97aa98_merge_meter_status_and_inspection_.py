"""merge meter status and inspection numeric type

Revision ID: e5225e97aa98
Revises: 4fb99c7c5b19, cf4c7753dac5
Create Date: 2026-07-13 13:48:46.396284
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5225e97aa98'
down_revision: Union[str, None] = ('4fb99c7c5b19', 'cf4c7753dac5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
