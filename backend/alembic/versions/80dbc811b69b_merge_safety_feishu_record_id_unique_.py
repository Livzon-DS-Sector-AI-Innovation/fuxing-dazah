"""merge safety feishu_record_id unique index

Revision ID: 80dbc811b69b
Revises: 2af364a150a5, aafcd7443df9
Create Date: 2026-06-30 14:33:42.709635
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80dbc811b69b'
down_revision: Union[str, None] = ('2af364a150a5', 'aafcd7443df9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
