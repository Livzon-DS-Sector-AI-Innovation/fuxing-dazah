"""merge offer tables upstream

Revision ID: 815c338bf916
Revises: 9741f88ac586, cafc625b65ee
Create Date: 2026-07-21 09:15:56.103020
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '815c338bf916'
down_revision: Union[str, None] = ('9741f88ac586', 'cafc625b65ee')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
