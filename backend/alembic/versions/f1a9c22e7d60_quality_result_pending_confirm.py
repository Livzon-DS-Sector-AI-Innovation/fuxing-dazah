"""quality result pending_confirm

Revision ID: f1a9c22e7d60
Revises: a0c4d16f0202
Create Date: 2026-11-05 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9c22e7d60'
down_revision: Union[str, None] = 'a0c4d16f0202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quality_test_results',
        sa.Column('pending_confirm', sa.Boolean(), server_default='false', nullable=False,
                  comment='解析自动填入待人工确认（确认后正式归入）'),
        schema='quality',
    )


def downgrade() -> None:
    op.drop_column('quality_test_results', 'pending_confirm', schema='quality')
