"""add_remark_to_instrument_and_gas_detector

Revision ID: 717564ddd4e0
Revises: e22654fa1b3c
Create Date: 2026-07-07 16:34:12.039844
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '717564ddd4e0'
down_revision: Union[str, None] = 'e22654fa1b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instrument_records',
        sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
        schema='meter',
    )
    op.add_column(
        'gas_detector_records',
        sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
        schema='meter',
    )


def downgrade() -> None:
    op.drop_column('gas_detector_records', 'remark', schema='meter')
    op.drop_column('instrument_records', 'remark', schema='meter')
