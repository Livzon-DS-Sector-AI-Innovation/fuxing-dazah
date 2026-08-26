"""add onboarding_tasks and review_type

Revision ID: c8e237f1211c
Revises: 123c76fb698d
Create Date: 2026-08-07 15:27:58.531003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e237f1211c'
down_revision: Union[str, None] = '123c76fb698d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 入职子任务表
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('onboarding_tasks',
        sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
        sa.Column('task_type', sa.String(length=32), nullable=False, comment='任务类型：体检/资料审核/合同签署/入职培训'),
        sa.Column('status', sa.String(length=16), server_default='待完成', nullable=False, comment='待完成 / 已完成'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序'),
        sa.Column('completed_at', sa.DateTime(), nullable=True, comment='完成时间'),
        sa.Column('completed_by', sa.String(length=64), nullable=True, comment='完成人'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_onboarding_tasks_candidate', 'onboarding_tasks', ['candidate_id'], unique=False, schema='hr')

    # candidate_reviews 新增 review_type 列
    op.add_column('candidate_reviews',
        sa.Column('review_type', sa.String(length=16), server_default='部门审核', nullable=False,
                  comment='部门审核 / 入职审批'),
        schema='hr')


def downgrade() -> None:
    op.drop_index('ix_onboarding_tasks_candidate', table_name='onboarding_tasks', schema='hr')
    op.drop_table('onboarding_tasks', schema='hr')
    op.drop_column('candidate_reviews', 'review_type', schema='hr')
