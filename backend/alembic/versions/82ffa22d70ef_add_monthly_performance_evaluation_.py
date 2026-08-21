"""add monthly performance evaluation tables

Revision ID: 82ffa22d70ef
Revises: departure_cert_sign_001
Create Date: 2026-08-03 18:11:43.703894
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82ffa22d70ef'
down_revision: Union[str, None] = 'departure_cert_sign_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")

    op.create_table('monthly_performance_evaluations',
    sa.Column('department', sa.String(length=128), nullable=False, comment='部门名称'),
    sa.Column('department_head', sa.String(length=64), nullable=False, comment='部门负责人姓名'),
    sa.Column('evaluator_leader', sa.String(length=64), nullable=True, comment='分管领导姓名'),
    sa.Column('evaluation_month', sa.String(length=7), nullable=False, comment='考核月份 YYYY-MM'),
    sa.Column('headcount', sa.Integer(), nullable=True, comment='考核定编'),
    sa.Column('status', sa.String(length=16), server_default='draft', nullable=False, comment='状态: draft/self_submitted/leader_scored/confirmed'),
    sa.Column('self_submitted_at', sa.DateTime(timezone=True), nullable=True, comment='自评提交时间'),
    sa.Column('leader_submitted_at', sa.DateTime(timezone=True), nullable=True, comment='领导评分提交时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_mpe_department', 'monthly_performance_evaluations', ['department'], unique=False, schema='hr')
    op.create_index('ix_mpe_month', 'monthly_performance_evaluations', ['evaluation_month'], unique=False, schema='hr')
    op.create_index('ix_mpe_status', 'monthly_performance_evaluations', ['status'], unique=False, schema='hr')

    op.create_table('performance_evaluation_items',
    sa.Column('evaluation_id', sa.Uuid(), nullable=False, comment='关联考核主表'),
    sa.Column('category', sa.String(length=16), nullable=False, comment='类别: key_work/routine_work/reward_penalty'),
    sa.Column('indicator', sa.String(length=256), nullable=False, comment='考核指标'),
    sa.Column('standard', sa.String(length=512), nullable=True, comment='考核标准/目标'),
    sa.Column('weight', sa.Float(), nullable=False, comment='权重(%)'),
    sa.Column('self_score', sa.Float(), nullable=True, comment='自评分'),
    sa.Column('leader_score', sa.Float(), nullable=True, comment='分管领导评分'),
    sa.Column('final_score', sa.Float(), nullable=True, comment='核定分'),
    sa.Column('completion', sa.String(length=512), nullable=True, comment='完成情况'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['evaluation_id'], ['hr.monthly_performance_evaluations.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_pei_evaluation_id', 'performance_evaluation_items', ['evaluation_id'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_pei_evaluation_id', table_name='performance_evaluation_items', schema='hr')
    op.drop_table('performance_evaluation_items', schema='hr')
    op.drop_index('ix_mpe_status', table_name='monthly_performance_evaluations', schema='hr')
    op.drop_index('ix_mpe_month', table_name='monthly_performance_evaluations', schema='hr')
    op.drop_index('ix_mpe_department', table_name='monthly_performance_evaluations', schema='hr')
    op.drop_table('monthly_performance_evaluations', schema='hr')
