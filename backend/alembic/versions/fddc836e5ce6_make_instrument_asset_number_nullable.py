"""make_instrument_asset_number_nullable

Revision ID: fddc836e5ce6
Revises: 00eeb8dd4525
Create Date: 2026-07-01 09:13:27.320039
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fddc836e5ce6'
down_revision: Union[str, None] = '00eeb8dd4525'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('instrument_records', 'asset_number',
                    existing_type=sa.VARCHAR(length=80),
                    nullable=True,
                    existing_comment='资产编号',
                    schema='meter')


def downgrade() -> None:
    op.alter_column('instrument_records', 'asset_number',
                    existing_type=sa.VARCHAR(length=80),
                    nullable=False,
                    existing_comment='资产编号',
                    schema='meter')
