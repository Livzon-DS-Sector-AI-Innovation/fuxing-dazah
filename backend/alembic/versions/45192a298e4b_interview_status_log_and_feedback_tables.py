"""interview status log and feedback tables

面试状态流转日志 + 人工面试评价两张新表（hr schema 已存在，无需 CREATE SCHEMA）。

Revision ID: 45192a298e4b
Revises: 8f9ab7c5861e
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45192a298e4b'
down_revision: Union[str, None] = '8f9ab7c5861e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅保留面试状态日志/人工评价两张表的 DDL（autogenerate 混入的其他模块差异已按规范清理）
    op.create_table('interview_feedbacks',
    sa.Column('interview_id', sa.Uuid(), nullable=False, comment='面试ID'),
    sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
    sa.Column('evaluator', sa.String(length=64), nullable=False, comment='评价人（面试官）'),
    sa.Column('dimensions', sa.JSON(), nullable=True, comment='维度评分 [{name, score(1-5), comment}]'),
    sa.Column('overall_comment', sa.Text(), nullable=True, comment='总体评价'),
    sa.Column('result', sa.String(length=16), nullable=False, comment='结论：通过/待定/不通过'),
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
    op.create_index('uq_if_interview', 'interview_feedbacks', ['interview_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('interview_status_logs',
    sa.Column('interview_id', sa.Uuid(), nullable=False, comment='面试ID'),
    sa.Column('from_status', sa.String(length=16), nullable=True, comment='原状态'),
    sa.Column('to_status', sa.String(length=16), nullable=False, comment='新状态'),
    sa.Column('operator', sa.String(length=64), nullable=True, comment='操作人'),
    sa.Column('remark', sa.String(length=256), nullable=True, comment='备注'),
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
    op.create_index('ix_isl_interview_id', 'interview_status_logs', ['interview_id'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_isl_interview_id', table_name='interview_status_logs', schema='hr')
    op.drop_table('interview_status_logs', schema='hr')
    op.drop_index('uq_if_interview', table_name='interview_feedbacks', schema='hr')
    op.drop_table('interview_feedbacks', schema='hr')
