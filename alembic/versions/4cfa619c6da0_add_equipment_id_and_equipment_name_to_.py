"""add equipment_id and equipment_name to energy_device_configs

Revision ID: 4cfa619c6da0
Revises: b5460b38ce84
Create Date: 2026-07-15 16:00:55.715344
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4cfa619c6da0'
down_revision: Union[str, None] = 'b5460b38ce84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column('equipment_id', sa.UUID(), nullable=True, comment='关联设备管理中的设备ID'),
        schema='energy',
    )
    op.add_column(
        'energy_device_configs',
        sa.Column('equipment_name', sa.String(length=200), nullable=True, comment='关联设备名称（冗余存储，便于展示）'),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_device_configs', 'equipment_name', schema='energy')
    op.drop_column('energy_device_configs', 'equipment_id', schema='energy')
