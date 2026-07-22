"""add color to energy_type_configs

Revision ID: b5460b38ce84
Revises: a952ff1636f5
Create Date: 2026-07-15 15:28:17.940785
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5460b38ce84'
down_revision: Union[str, None] = 'a952ff1636f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.add_column(
        'energy_type_configs',
        sa.Column('color', sa.String(length=20), nullable=True, comment='卡片颜色'),
        schema='energy',
    )
    # 预置 7 种能源的颜色
    colors = [
        ('electricity', '#0075de'), ('water', '#1aae39'), ('steam', '#dd5b00'),
        ('cooling', '#722ed1'), ('compressed_air', '#2f54eb'),
        ('nitrogen', '#fa541c'), ('natural_gas', '#faad14'),
    ]
    for tc, c in colors:
        op.execute(
            f"UPDATE energy.energy_type_configs SET color = '{c}' WHERE type_code = '{tc}' AND is_deleted = false"
        )


def downgrade() -> None:
    op.drop_column('energy_type_configs', 'color', schema='energy')
