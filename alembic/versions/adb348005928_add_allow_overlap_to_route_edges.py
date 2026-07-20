"""add allow_overlap to route_edges

Revision ID: adb348005928
Revises: 5e4fc970632b
Create Date: 2026-07-20 09:47:06.829740
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'adb348005928'
down_revision: Union[str, None] = '5e4fc970632b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'route_edges',
        sa.Column('allow_overlap', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment='允许前道工序未完成时开始本工序（流水线模式）'),
        schema='production',
    )


def downgrade() -> None:
    op.drop_column('route_edges', 'allow_overlap', schema='production')
