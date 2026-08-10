"""add collect_granularity to energy_type_configs, remove stat_role from energy_device_configs

Revision ID: b1c2d3e4f5a6
Revises: a27cd8fceae4
Create Date: 2026-08-07 11:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a27cd8fceae4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新增 collect_granularity 列（默认 hourly）
    op.add_column(
        'energy_type_configs',
        sa.Column(
            'collect_granularity',
            sa.String(10),
            nullable=False,
            server_default='hourly',
            comment='采集粒度: hourly=逐小时, daily=日汇总',
        ),
        schema='energy',
    )

    # 2. 清理 stat_role='excluded' 的设备（禁用以避免被统计）
    op.execute(
        "UPDATE energy.energy_device_configs SET is_enabled = FALSE WHERE stat_role = 'excluded'"
    )

    # 3. 删除 stat_role CHECK 约束和列
    op.drop_constraint(
        'ck_energy_device_config_stat_role',
        'energy_device_configs',
        schema='energy',
        type_='check',
    )
    op.drop_column('energy_device_configs', 'stat_role', schema='energy')


def downgrade() -> None:
    # 恢复 stat_role 列
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

    # 恢复 is_enabled（无法精确逆操作，仅恢复可以推断的）
    op.execute(
        "UPDATE energy.energy_device_configs SET is_enabled = TRUE WHERE stat_role = 'excluded'"
    )

    # 删除 collect_granularity 列
    op.drop_column('energy_type_configs', 'collect_granularity', schema='energy')
