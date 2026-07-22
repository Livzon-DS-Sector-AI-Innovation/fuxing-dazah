"""add training_evaluations table

Revision ID: 55b6248f4aee
Revises: c637e4490bab
Create Date: 2026-07-01 10:31:39.884763
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '55b6248f4aee'
down_revision: Union[str, None] = 'c637e4490bab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('training_evaluations',
        sa.Column('id', sa.Uuid(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('training_content', sa.String(512), nullable=True, comment='培训内容'),
        sa.Column('training_date', sa.Date(), nullable=True, comment='培训日期'),
        sa.Column('trainer', sa.String(64), nullable=True, comment='培训师'),
        sa.Column('training_method', sa.String(32), nullable=True, comment='培训方式'),
        sa.Column('assessment_method', sa.String(32), nullable=True, comment='考核方式'),
        sa.Column('trainee_names', sa.Text(), nullable=True, comment='培训对象'),
        sa.Column('expected_count', sa.Integer(), nullable=True),
        sa.Column('actual_count', sa.Integer(), nullable=True),
        sa.Column('exam_count', sa.Integer(), nullable=True),
        sa.Column('excellent_count', sa.Integer(), nullable=True),
        sa.Column('qualified_count', sa.Integer(), nullable=True),
        sa.Column('unqualified_count', sa.Integer(), nullable=True),
        sa.Column('sick_leave', sa.Integer(), nullable=True),
        sa.Column('personal_leave', sa.Integer(), nullable=True),
        sa.Column('maternity_leave', sa.Integer(), nullable=True),
        sa.Column('absent_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false')),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_table('training_evaluations', schema='hr')
