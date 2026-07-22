"""add daily_collect_time to energy_device_configs

Revision ID: 172a514dc1ef
Revises: 4cfa619c6da0
Create Date: 2026-07-16 08:56:46.021114
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '172a514dc1ef'
down_revision: Union[str, None] = '4cfa619c6da0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column('daily_collect_time', sa.String(length=5), nullable=True,
                  comment="按天采集的触发时间 HH:MM，如 08:00；NULL 表示按小时采集"),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_device_configs', 'daily_collect_time', schema='energy')
