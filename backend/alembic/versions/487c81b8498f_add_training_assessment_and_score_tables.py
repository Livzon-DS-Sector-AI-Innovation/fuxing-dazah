"""add training assessment and score tables

Revision ID: 487c81b8498f
Revises: 20fda41cfdd3
Create Date: 2026-07-16 16:38:00.943755
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '487c81b8498f'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('training_assessments',
    sa.Column('subject', sa.String(length=256), nullable=False, comment='培训内容/主题'),
    sa.Column('department', sa.String(length=64), nullable=True, comment='培训部门/对象'),
    sa.Column('training_date', sa.Date(), nullable=True, comment='培训日期'),
    sa.Column('training_method', sa.String(length=32), nullable=True, comment='培训方式'),
    sa.Column('assessment_method', sa.String(length=32), server_default='问答', nullable=False, comment='考核方式'),
    sa.Column('trainer', sa.String(length=64), nullable=True, comment='培训师'),
    sa.Column('questions', sa.JSON(), nullable=True, comment='题目快照 [{file_no,question,answer,score}]'),
    sa.Column('question_count', sa.Integer(), server_default='10', nullable=False, comment='题目数量'),
    sa.Column('full_score', sa.Integer(), server_default='100', nullable=False, comment='满分'),
    sa.Column('excellent_line', sa.Integer(), server_default='90', nullable=False, comment='优秀线（总分≥该值为优）'),
    sa.Column('pass_line', sa.Integer(), server_default='80', nullable=False, comment='合格线（总分≥该值为合格）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_training_assessments_department', 'training_assessments', ['department'], unique=False, schema='hr')
    op.create_index('ix_training_assessments_training_date', 'training_assessments', ['training_date'], unique=False, schema='hr')
    op.create_table('training_assessment_scores',
    sa.Column('assessment_id', sa.Uuid(), nullable=False, comment='考核场次ID（逻辑关联，无外键）'),
    sa.Column('employee_name', sa.String(length=64), nullable=False, comment='姓名'),
    sa.Column('employee_number', sa.String(length=32), nullable=True, comment='工号'),
    sa.Column('wrong_questions', sa.JSON(), nullable=True, comment='错题序号列表，空为全对'),
    sa.Column('total_score', sa.Integer(), server_default='0', nullable=False, comment='总分'),
    sa.Column('grade', sa.String(length=16), nullable=True, comment='等级：优/合格/不合格'),
    sa.Column('result_text', sa.String(length=256), nullable=True, comment='得分情况文字'),
    sa.Column('assessed_date', sa.Date(), nullable=True, comment='考核日期'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_training_assessment_scores_assessment_id', 'training_assessment_scores', ['assessment_id'], unique=False, schema='hr')
    op.create_index('ix_training_assessment_scores_employee_number', 'training_assessment_scores', ['employee_number'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_training_assessment_scores_employee_number', table_name='training_assessment_scores', schema='hr')
    op.drop_index('ix_training_assessment_scores_assessment_id', table_name='training_assessment_scores', schema='hr')
    op.drop_table('training_assessment_scores', schema='hr')
    op.drop_index('ix_training_assessments_training_date', table_name='training_assessments', schema='hr')
    op.drop_index('ix_training_assessments_department', table_name='training_assessments', schema='hr')
    op.drop_table('training_assessments', schema='hr')
