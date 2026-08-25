"""remove collection_interval and daily_collect_time from energy device configs

Revision ID: 98926345fc1c
Revises: ff497f1c138b
Create Date: 2026-08-04 15:47:24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98926345fc1c'
down_revision: Union[str, None] = 'ff497f1c138b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'ck_energy_device_config_interval_positive',
        'energy_device_configs',
        schema='energy',
        type_='check',
    )
    op.drop_column('energy_device_configs', 'daily_collect_time', schema='energy')
    op.drop_column('energy_device_configs', 'collection_interval', schema='energy')


def downgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column('collection_interval', sa.Integer(), nullable=False,
                  server_default='60', comment='采集间隔(分钟)'),
        schema='energy',
    )
    op.add_column(
        'energy_device_configs',
        sa.Column('daily_collect_time', sa.String(5), nullable=True,
                  comment='按天采集的触发时间 HH:MM'),
        schema='energy',
    )
    op.create_check_constraint(
        'ck_energy_device_config_interval_positive',
        'energy_device_configs',
        'collection_interval > 0',
        schema='energy',
    )
