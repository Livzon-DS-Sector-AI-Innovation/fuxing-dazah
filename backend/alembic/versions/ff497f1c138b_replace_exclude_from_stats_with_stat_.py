"""replace exclude_from_stats with stat_role enum

Revision ID: ff497f1c138b
Revises: 852441e765d4
Create Date: 2026-08-03 11:25:15.898919
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff497f1c138b'
down_revision: Union[str, None] = '852441e765d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新增 stat_role 列
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
    # 2. 添加 CHECK 约束
    op.create_check_constraint(
        'ck_energy_device_config_stat_role',
        'energy_device_configs',
        "stat_role IN ('normal', 'excluded', 'total')",
        schema='energy',
    )
    # 3. 迁移现有数据: exclude_from_stats=true → stat_role='excluded'
    op.execute("UPDATE energy.energy_device_configs SET stat_role = 'excluded' WHERE exclude_from_stats = true")
    # 4. 删除旧列
    op.drop_column('energy_device_configs', 'exclude_from_stats', schema='energy')


def downgrade() -> None:
    # 1. 恢复旧列
    op.add_column(
        'energy_device_configs',
        sa.Column(
            'exclude_from_stats',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='是否不参与能源总耗统计与可视化',
        ),
        schema='energy',
    )
    # 2. 回迁数据
    op.execute("UPDATE energy.energy_device_configs SET exclude_from_stats = true WHERE stat_role = 'excluded'")
    # 3. 删除 CHECK 约束
    op.drop_constraint(
        'ck_energy_device_config_stat_role',
        'energy_device_configs',
        schema='energy',
        type_='check',
    )
    # 4. 删除 stat_role 列
    op.drop_column('energy_device_configs', 'stat_role', schema='energy')
