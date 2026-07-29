"""add is_region_level to energy_device_configs

Revision ID: 0e523a3065b2
Revises: 40b14a351215
Create Date: 2026-07-28 08:56:07.734703
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e523a3065b2'
down_revision: Union[str, None] = '40b14a351215'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column('is_region_level', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment='是否区域级别（False=部门级别）'),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_device_configs', 'is_region_level', schema='energy')
