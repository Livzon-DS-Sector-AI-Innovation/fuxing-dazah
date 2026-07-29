"""add hr question bank table

Revision ID: fefe16a31b9d
Revises: 487c81b8498f
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fefe16a31b9d'
down_revision: Union[str, None] = '487c81b8498f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('question_bank',
    sa.Column('file_no', sa.String(length=64), server_default='', nullable=False, comment='文件编号（SOP编号）'),
    sa.Column('subject', sa.String(length=256), nullable=True, comment='培训内容/主题'),
    sa.Column('question', sa.Text(), nullable=False, comment='考题'),
    sa.Column('answer', sa.Text(), server_default='', nullable=False, comment='答案'),
    sa.Column('score', sa.Integer(), server_default='10', nullable=False, comment='默认分值'),
    sa.Column('source', sa.String(length=16), server_default='手工录入', nullable=False, comment='来源：AI生成/手工录入/历史导入'),
    sa.Column('department', sa.String(length=64), nullable=True, comment='适用部门'),
    sa.Column('usage_count', sa.Integer(), server_default='0', nullable=False, comment='被组卷使用次数'),
    sa.Column('last_used_date', sa.Date(), nullable=True, comment='最近使用日期'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_question_bank_department', 'question_bank', ['department'], unique=False, schema='hr')
    op.create_index('ix_question_bank_file_no', 'question_bank', ['file_no'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_question_bank_file_no', table_name='question_bank', schema='hr')
    op.drop_index('ix_question_bank_department', table_name='question_bank', schema='hr')
    op.drop_table('question_bank', schema='hr')
