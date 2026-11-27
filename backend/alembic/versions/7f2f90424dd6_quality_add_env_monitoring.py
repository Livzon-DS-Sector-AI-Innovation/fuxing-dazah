"""quality add env monitoring

Revision ID: 7f2f90424dd6
Revises: 1383f15790c1
Create Date: 2026-10-21 17:54:54.035639
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f2f90424dd6'
down_revision: str | None = '1383f15790c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    # 监测点台账
    op.create_table(
        'quality_env_points',
        sa.Column('room', sa.String(length=128), nullable=False, comment='房间/区域'),
        sa.Column('point_no', sa.String(length=64), nullable=False, comment='点位编号'),
        sa.Column('monitor_type', sa.String(length=32), nullable=False,
                  comment='settle 沉降菌 / float 浮游菌 / particle 悬浮粒子 / temp_humidity 温湿度 / pressure 压差'),
        sa.Column('frequency', sa.String(length=32), nullable=True,
                  comment='监测频次 per_batch 每批 / weekly 每周 / monthly 每月（3b 周期计划用）'),
        sa.Column('alert_limit', sa.Float(), nullable=True, comment='警戒限'),
        sa.Column('action_limit', sa.Float(), nullable=True, comment='行动限'),
        sa.Column('status', sa.String(length=16), server_default='active', nullable=False,
                  comment='active 启用 / inactive 停用'),
        sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_env_point_room', 'quality_env_points', ['room'], unique=False, schema='quality')
    op.create_index('ix_quality_env_point_no', 'quality_env_points', ['point_no'], unique=False, schema='quality')
    # 监测记录
    op.create_table(
        'quality_env_records',
        sa.Column('point_id', sa.Uuid(), nullable=False, comment='监测点，逻辑引用 quality_env_points.id'),
        sa.Column('record_date', sa.String(length=32), nullable=False, comment='监测日期 YYYY-MM-DD'),
        sa.Column('result_value', sa.Float(), nullable=True, comment='检测结果值'),
        sa.Column('alert_limit', sa.Float(), nullable=True, comment='判定时警戒限快照'),
        sa.Column('action_limit', sa.Float(), nullable=True, comment='判定时行动限快照'),
        sa.Column('judge', sa.String(length=16), nullable=True, comment='pass 合格 / alert 超警戒 / action 超行动'),
        sa.Column('recorded_by', sa.Uuid(), nullable=True, comment='填报人，逻辑引用 identity.users.id'),
        sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_env_record_point', 'quality_env_records', ['point_id'], unique=False, schema='quality')
    op.create_index('ix_quality_env_record_date', 'quality_env_records', ['record_date'], unique=False, schema='quality')


def downgrade() -> None:
    op.drop_index('ix_quality_env_record_date', table_name='quality_env_records', schema='quality')
    op.drop_index('ix_quality_env_record_point', table_name='quality_env_records', schema='quality')
    op.drop_table('quality_env_records', schema='quality')
    op.drop_index('ix_quality_env_point_no', table_name='quality_env_points', schema='quality')
    op.drop_index('ix_quality_env_point_room', table_name='quality_env_points', schema='quality')
    op.drop_table('quality_env_points', schema='quality')
