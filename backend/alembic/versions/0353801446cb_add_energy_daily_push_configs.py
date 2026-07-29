"""add_energy_daily_push_configs

Revision ID: 0353801446cb
Revises: 0e523a3065b2
Create Date: 2026-07-28 10:20:44.529089
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0353801446cb'
down_revision: Union[str, None] = '0e523a3065b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('energy_daily_push_configs',
    sa.Column('name', sa.String(length=200), nullable=False, comment='配置名称'),
    sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='是否启用'),
    sa.Column('notify_time', sa.String(length=5), nullable=True, comment='每日定时推送时间 HH:MM，如 09:00；NULL 表示仅手动推送'),
    sa.Column('notify_users', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='接收人列表 JSON: [{"name": "张三", "feishu_open_id": "ou_xxx"}]'),
    sa.Column('solar_device_id', sa.UUID(), nullable=True, comment='光伏发电设备配置ID'),
    sa.Column('pressure_device_id', sa.UUID(), nullable=True, comment='蒸汽差压发电设备配置ID'),
    sa.Column('rto1_gas_device_id', sa.UUID(), nullable=True, comment='一期RTO用气设备配置ID'),
    sa.Column('rto2_gas_device_id', sa.UUID(), nullable=True, comment='二期RTO用气设备配置ID'),
    sa.Column('rto1_elec_device_id', sa.UUID(), nullable=True, comment='一期RTO用电设备配置ID'),
    sa.Column('rto2_elec_device_id', sa.UUID(), nullable=True, comment='二期RTO用电设备配置ID'),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True, comment='上次推送时间'),
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
    schema='energy'
    )


def downgrade() -> None:
    op.drop_table('energy_daily_push_configs', schema='energy')
