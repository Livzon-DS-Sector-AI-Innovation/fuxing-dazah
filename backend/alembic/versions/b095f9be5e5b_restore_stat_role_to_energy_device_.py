"""restore stat_role to energy_device_configs

Revision ID: b095f9be5e5b
Revises: 3a67a9fd06b2
Create Date: 2026-08-10 09:07:34
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b095f9be5e5b'
down_revision: str | None = '3a67a9fd06b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column(
            'stat_role',
            sa.String(20),
            nullable=False,
            server_default='normal',
            comment='统计角色: normal=参与加和, excluded=不参与, total=直接作为总耗',
        ),
        schema='energy',
    )
    op.create_check_constraint(
        'ck_energy_device_config_stat_role',
        'energy_device_configs',
        "stat_role IN ('normal', 'excluded', 'total')",
        schema='energy',
    )


def downgrade() -> None:
    op.drop_constraint(
        'ck_energy_device_config_stat_role',
        'energy_device_configs',
        schema='energy',
        type_='check',
    )
    op.drop_column('energy_device_configs', 'stat_role', schema='energy')
