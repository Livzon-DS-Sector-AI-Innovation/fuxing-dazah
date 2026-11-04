"""quality add container location

Revision ID: 46c87af24fab
Revises: 52e2fb013544
Create Date: 2026-10-13 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '46c87af24fab'
down_revision: Union[str, None] = '52e2fb013544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_material_containers', sa.Column('location', sa.String(length=50), nullable=True, comment='库位（货架编号，如 A-01-03）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_material_containers', 'location', schema='quality')
