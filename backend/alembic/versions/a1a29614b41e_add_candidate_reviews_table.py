"""add candidate_reviews table

Revision ID: a1a29614b41e
Revises: 4a36bb508376
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1a29614b41e'
down_revision: Union[str, None] = '4a36bb508376'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('candidate_reviews',
        sa.Column('candidate_id', sa.Uuid(), nullable=False, comment='候选人ID'),
        sa.Column('job_requirement_id', sa.Uuid(), nullable=True, comment='关联岗位需求'),
        sa.Column('pushed_by', sa.String(64), nullable=True, comment='推送人(HR)'),
        sa.Column('push_note', sa.Text(), nullable=True, comment='推送备注'),
        sa.Column('reviewer', sa.String(64), nullable=True, comment='审核人(用人部门负责人)'),
        sa.Column('status', sa.String(16), server_default='待审核', nullable=False, comment='待审核/已同意/已拒绝'),
        sa.Column('review_comment', sa.Text(), nullable=True, comment='审核意见'),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True, comment='审核时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_cr_candidate_id', 'candidate_reviews', ['candidate_id'], unique=False, schema='hr')
    op.create_index('ix_cr_status', 'candidate_reviews', ['status'], unique=False, schema='hr')
    op.create_index('ix_cr_reviewer', 'candidate_reviews', ['reviewer'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_cr_reviewer', table_name='candidate_reviews', schema='hr')
    op.drop_index('ix_cr_status', table_name='candidate_reviews', schema='hr')
    op.drop_index('ix_cr_candidate_id', table_name='candidate_reviews', schema='hr')
    op.drop_table('candidate_reviews', schema='hr')
