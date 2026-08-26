"""add performance categories and scores

Revision ID: 89f4118d713f
Revises: 82ffa22d70ef
Create Date: 2026-08-04 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '89f4118d713f'
down_revision: Union[str, None] = '82ffa22d70ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('performance_categories',
    sa.Column('name', sa.String(length=64), nullable=False, comment='考核项目名称'),
    sa.Column('weight', sa.Float(), nullable=False, comment='权重(%)'),
    sa.Column('evaluator', sa.String(length=64), nullable=True, comment='项目负责人姓名'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
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
    op.create_index('ix_pc_is_active', 'performance_categories', ['is_active'], unique=False, schema='hr')

    op.create_table('performance_category_scores',
    sa.Column('evaluation_id', sa.Uuid(), nullable=False, comment='关联考核主表'),
    sa.Column('category_id', sa.Uuid(), nullable=False, comment='关联考核项目'),
    sa.Column('score', sa.Float(), nullable=True, comment='分数(0-100)'),
    sa.Column('scored_by', sa.String(length=64), nullable=True, comment='评分人'),
    sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True, comment='评分时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['hr.performance_categories.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['evaluation_id'], ['hr.monthly_performance_evaluations.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_pcs_category_id', 'performance_category_scores', ['category_id'], unique=False, schema='hr')
    op.create_index('ix_pcs_evaluation_id', 'performance_category_scores', ['evaluation_id'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_pcs_evaluation_id', table_name='performance_category_scores', schema='hr')
    op.drop_index('ix_pcs_category_id', table_name='performance_category_scores', schema='hr')
    op.drop_table('performance_category_scores', schema='hr')
    op.drop_index('ix_pc_is_active', table_name='performance_categories', schema='hr')
    op.drop_table('performance_categories', schema='hr')
