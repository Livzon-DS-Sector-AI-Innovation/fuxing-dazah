"""add_energy_workshop_config_and_alert_workshop_fields

Revision ID: 159d4edfef7e
Revises: 172a514dc1ef
Create Date: 2026-07-17 09:56:33.293885
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '159d4edfef7e'
down_revision: Union[str, None] = '172a514dc1ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")

    # ── 新增 energy_workshop_configs 表 ──
    op.create_table('energy_workshop_configs',
    sa.Column('workshop', sa.String(length=100), nullable=False, comment='车间名称（与 EnergyDeviceConfig.workshop 对应）'),
    sa.Column('heads', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='负责人列表 JSON: [{"name": "张三", "feishu_open_id": "ou_xxx"}]'),
    sa.Column('auto_notify_enabled', sa.Boolean(), nullable=False, comment='是否启用自动预警通知'),
    sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='是否启用该车间配置'),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True, comment='上次预警检查时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workshop', 'is_deleted', name='uq_energy_workshop_config_workshop'),
    schema='energy'
    )

    # ── energy_alert_records 新增 workshop 列 ──
    op.add_column('energy_alert_records', sa.Column('workshop', sa.String(length=100), nullable=True, comment='关联车间（车间预警使用）'), schema='energy')

    # ── energy_alert_rules 新增 workshop 和 is_system 列 ──
    op.add_column('energy_alert_rules', sa.Column('workshop', sa.String(length=100), nullable=True, comment='关联车间（系统规则按车间绑定）'), schema='energy')
    op.add_column('energy_alert_rules', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='是否系统自动生成'), schema='energy')


def downgrade() -> None:
    op.drop_column('energy_alert_rules', 'is_system', schema='energy')
    op.drop_column('energy_alert_rules', 'workshop', schema='energy')
    op.drop_column('energy_alert_records', 'workshop', schema='energy')
    op.drop_table('energy_workshop_configs', schema='energy')
