"""add exam paper table

Revision ID: d02196edd429
Revises: 12c35e21fee6
Create Date: 2026-07-17 14:10:21.945236
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd02196edd429'
down_revision: Union[str, None] = '12c35e21fee6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('exam_papers',
    sa.Column('subject', sa.String(length=256), nullable=False, comment='培训内容/主题'),
    sa.Column('department', sa.String(length=64), nullable=True, comment='培训部门'),
    sa.Column('training_date', sa.Date(), nullable=True, comment='培训日期'),
    sa.Column('training_method', sa.String(length=32), nullable=True, comment='培训方式'),
    sa.Column('questions', sa.JSON(), nullable=True, comment='题目快照[{type,question,options,answer,score}]'),
    sa.Column('full_score', sa.Integer(), server_default='100', nullable=False, comment='满分'),
    sa.Column('pass_line', sa.Integer(), server_default='60', nullable=False, comment='及格线'),
    sa.Column('choice_count', sa.Integer(), server_default='0', nullable=False, comment='单选题数'),
    sa.Column('true_false_count', sa.Integer(), server_default='0', nullable=False, comment='判断题数'),
    sa.Column('multi_choice_count', sa.Integer(), server_default='0', nullable=False, comment='多选题数'),
    sa.Column('fill_blank_count', sa.Integer(), server_default='0', nullable=False, comment='填空题数'),
    sa.Column('source', sa.String(length=16), server_default='AI生成', nullable=False, comment='来源'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_exam_papers_department', 'exam_papers', ['department'], unique=False, schema='hr')
    op.create_index('ix_exam_papers_subject', 'exam_papers', ['subject'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_exam_papers_subject', table_name='exam_papers', schema='hr')
    op.drop_index('ix_exam_papers_department', table_name='exam_papers', schema='hr')
    op.drop_table('exam_papers', schema='hr')
