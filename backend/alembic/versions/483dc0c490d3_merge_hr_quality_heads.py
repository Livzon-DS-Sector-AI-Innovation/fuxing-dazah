"""merge_hr_quality_heads

Revision ID: 483dc0c490d3
Revises: 36d314a558f2, e00e006eea52
Create Date: 2026-07-30 19:27:42.903755
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '483dc0c490d3'
down_revision: Union[str, None] = ('36d314a558f2', 'e00e006eea52')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
