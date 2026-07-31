"""merge 32c100f56e59 and 9f0d0b11b523

Revision ID: f9cccc30f41a
Revises: 32c100f56e59, 9f0d0b11b523
Create Date: 2026-07-31 14:56:04.834678
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9cccc30f41a'
down_revision: Union[str, None] = ('32c100f56e59', '9f0d0b11b523')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
