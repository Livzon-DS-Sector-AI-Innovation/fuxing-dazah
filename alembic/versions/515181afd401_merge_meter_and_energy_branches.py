"""merge meter and energy branches

Revision ID: 515181afd401
Revises: 55363db00b1f, 6a2b07b83bb1, ad1d772f4519, b661ba140908
Create Date: 2026-07-08 17:55:34.930606
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '515181afd401'
down_revision: Union[str, None] = ('55363db00b1f', '6a2b07b83bb1', 'ad1d772f4519', 'b661ba140908')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
