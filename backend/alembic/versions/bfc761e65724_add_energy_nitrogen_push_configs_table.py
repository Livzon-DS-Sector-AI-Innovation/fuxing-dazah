"""add energy_nitrogen_push_configs table

Revision ID: bfc761e65724
Revises: 0353801446cb
Create Date: 2026-07-28 14:10:47.284891
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bfc761e65724'
down_revision: Union[str, None] = '0353801446cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.create_table('energy_nitrogen_push_configs',
    sa.Column('name', sa.String(length=200), nullable=False, comment='配置名称'),
    sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='是否启用'),
    sa.Column('notify_time', sa.String(length=5), nullable=True, comment='每日定时推送时间 HH:MM，如 09:00；NULL 表示仅手动推送'),
    sa.Column('notify_users', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='接收人列表 JSON: [{"name": "张三", "feishu_open_id": "ou_xxx"}]'),
    sa.Column('nitrogen_device_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='氮气设备配置ID列表'),
    sa.Column('monthly_guaranteed_consumption', sa.Numeric(precision=18, scale=4), nullable=False, comment='月度保底消费量'),
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
    op.drop_table('energy_nitrogen_push_configs', schema='energy')
