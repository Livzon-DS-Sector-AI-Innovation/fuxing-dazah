"""merge hr fix batch2 and meter domain split

Revision ID: 84437cea925f
Revises: d30923217d5c, b2fix0000001
Create Date: 2026-08-31 00:42:08.996592
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84437cea925f'
down_revision: Union[str, None] = ('d30923217d5c', 'b2fix0000001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
