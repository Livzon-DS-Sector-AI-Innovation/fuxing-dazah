"""add_status_to_gas_detector_records

Revision ID: cf4c7753dac5
Revises: 1c3d4968c09c
Create Date: 2026-07-13 09:50:49.967358
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf4c7753dac5'
down_revision: Union[str, None] = '1c3d4968c09c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'gas_detector_records',
        sa.Column('status', sa.String(length=20), nullable=True, comment='器具状态：在用/停用/超期'),
        schema='meter',
    )
    op.alter_column(
        'instrument_records', 'status',
        existing_type=sa.VARCHAR(length=20),
        comment='器具状态：在用/停用/超期',
        existing_comment='器具状态：在用/停用',
        existing_nullable=True,
        schema='meter',
    )


def downgrade() -> None:
    op.alter_column(
        'instrument_records', 'status',
        existing_type=sa.VARCHAR(length=20),
        comment='器具状态：在用/停用',
        existing_comment='器具状态：在用/停用/超期',
        existing_nullable=True,
        schema='meter',
    )
    op.drop_column('gas_detector_records', 'status', schema='meter')
