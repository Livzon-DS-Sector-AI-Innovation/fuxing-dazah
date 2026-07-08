"""add energy_type_configs table

Revision ID: 7e70c41a9cdc
Revises: 241f68a331ab
Create Date: 2026-06-25 17:06:03.952420
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e70c41a9cdc'
down_revision: Union[str, None] = '241f68a331ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('energy_type_configs',
        sa.Column('type_code', sa.String(length=50), nullable=False, comment='唯一编码，如 electricity / electricity_workshop_a'),
        sa.Column('parent_code', sa.String(length=50), nullable=True, comment='父级编码，顶层分类为 NULL'),
        sa.Column('display_name', sa.String(length=100), nullable=False, comment='展示名称，如 电力 / 发酵车间用电'),
        sa.Column('unit', sa.String(length=20), nullable=False, comment='计量单位: kWh / m³ / t'),
        sa.Column('icon', sa.String(length=50), nullable=True, comment='图标标识'),
        sa.Column('sort_order', sa.Integer(), nullable=False, comment='排序权重，越小越靠前'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='启用状态，禁用后全局隐藏'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('type_code', 'is_deleted', name='uq_energy_type_config_code'),
        schema='energy'
    )


def downgrade() -> None:
    op.drop_table('energy_type_configs', schema='energy')
