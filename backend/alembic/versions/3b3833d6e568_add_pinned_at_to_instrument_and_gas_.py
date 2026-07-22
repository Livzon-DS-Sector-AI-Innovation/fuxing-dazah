"""add_pinned_at_to_instrument_and_gas_detector_records

Revision ID: 3b3833d6e568
Revises: e940c0e1d185
Create Date: 2026-07-02 18:02:50.924621
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b3833d6e568'
down_revision: Union[str, None] = 'e940c0e1d185'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instrument_records',
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True,
                  comment='最近一次上传报告的时间（用于列表置顶）'),
        schema='meter',
    )
    op.add_column(
        'gas_detector_records',
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True,
                  comment='最近一次上传报告的时间（用于列表置顶）'),
        schema='meter',
    )


def downgrade() -> None:
    op.drop_column('instrument_records', 'pinned_at', schema='meter')
    op.drop_column('gas_detector_records', 'pinned_at', schema='meter')
