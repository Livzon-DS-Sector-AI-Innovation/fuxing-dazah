"""safety app config center tables

安全模块 env→DB 迁移（2026-10-10）：应用配置中心两表。
生效优先级 = 进程 env（非空）> DB 活行（enabled 且 value 非空）> registry
代码默认（app/modules/safety/app_config/registry.py，82 键）；启动播种走
store.seed_from_env（only-missing，幂等），不在 migration 内播种——空库
部署（.env 仍有值）行为与迁移前完全一致，播种后清空 .env 键即完成切换。

Revision ID: c9f2a8e4d6b1
Revises: b7e4f1a9c3d2
Create Date: 2026-10-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9f2a8e4d6b1'
down_revision: str | None = 'b7e4f1a9c3d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('app_config_entries',
    sa.Column('key', sa.String(length=128), nullable=False, comment='配置键（= 原 env 变量名，registry 注册，DB 只能改值不能新增键）'),
    sa.Column('value', sa.String(length=1024), nullable=False, comment='配置值（字符串形态；bool 存 true/false，int 存十进制）'),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用（false 时本行不参与生效值计算，视为无 DB 行）'),
    sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('uq_app_config_entries_key', 'app_config_entries', ['key'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_app_config_entries_key', 'app_config_entries', ['key'], unique=False, schema='safety')

    op.create_table('app_config_audits',
    sa.Column('key', sa.String(length=128), nullable=False, comment='配置键'),
    sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable/seed'),
    sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前 compact（secret 键值脱敏）'),
    sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后 compact（secret 键值脱敏）'),
    sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name；启动播种为 system'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_app_config_audits_key_created', 'app_config_audits', ['key', 'created_at'], unique=False, schema='safety')
    op.create_index('idx_app_config_audits_created', 'app_config_audits', ['created_at'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('idx_app_config_audits_created', table_name='app_config_audits', schema='safety')
    op.drop_index('idx_app_config_audits_key_created', table_name='app_config_audits', schema='safety')
    op.drop_table('app_config_audits', schema='safety')
    op.drop_index('ix_app_config_entries_key', table_name='app_config_entries', schema='safety')
    op.drop_index('uq_app_config_entries_key', table_name='app_config_entries', schema='safety')
    op.drop_table('app_config_entries', schema='safety')
