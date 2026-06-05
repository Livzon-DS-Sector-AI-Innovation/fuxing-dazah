"""add energy tables

Revision ID: 5c291751e3d1
Revises: c3d4e5f6a7b8
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5c291751e3d1'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('energy_device_configs',
    sa.Column('platform_code', sa.String(length=50), nullable=False, comment='平台标识'),
    sa.Column('platform_device_code', sa.String(length=100), nullable=False, comment='三方平台设备/采集点编码'),
    sa.Column('device_name', sa.String(length=200), nullable=False, comment='设备名称'),
    sa.Column('energy_type', sa.String(length=20), nullable=False, comment='能源类型: electricity/steam/water'),
    sa.Column('api_endpoint', sa.String(length=500), nullable=False, comment='API 路径'),
    sa.Column('workshop', sa.String(length=100), nullable=False, comment='所属车间'),
    sa.Column('production_line', sa.String(length=100), nullable=False, comment='所属产线'),
    sa.Column('monitor_level', sa.String(length=20), nullable=False, comment='监控等级'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='计量单位'),
    sa.Column('collection_interval', sa.Integer(), nullable=False, comment='采集间隔(分钟)'),
    sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='是否启用采集'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("energy_type IN ('electricity', 'steam', 'water')", name='ck_energy_device_config_energy_type'),
    sa.CheckConstraint("monitor_level IN ('normal', 'important', 'urgent')", name='ck_energy_device_config_monitor_level'),
    sa.CheckConstraint('collection_interval > 0', name='ck_energy_device_config_interval_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('platform_code', 'platform_device_code', 'is_deleted', name='uq_energy_device_config_platform_device'),
    schema='energy'
    )
    op.create_table('energy_data',
    sa.Column('device_config_id', sa.Uuid(), nullable=False, comment='设备配置ID'),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, comment='数据时间点(小时粒度)'),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=False, comment='能耗累计值'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='计量单位'),
    sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='实际采集时间'),
    sa.Column('platform_raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='原始返回数据'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_config_id', 'timestamp', name='uq_energy_data_device_timestamp'),
    schema='energy'
    )
    op.create_table('energy_collect_logs',
    sa.Column('platform_code', sa.String(length=50), nullable=False, comment='采集的平台'),
    sa.Column('collect_time', sa.DateTime(timezone=True), nullable=False, comment='采集触发时间'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='状态: success/partial/failed'),
    sa.Column('device_count', sa.Integer(), nullable=False, comment='应采集设备数'),
    sa.Column('success_count', sa.Integer(), nullable=False, comment='成功条数'),
    sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
    sa.PrimaryKeyConstraint('id'),
    schema='energy'
    )


def downgrade() -> None:
    op.drop_table('energy_collect_logs', schema='energy')
    op.drop_table('energy_data', schema='energy')
    op.drop_table('energy_device_configs', schema='energy')
