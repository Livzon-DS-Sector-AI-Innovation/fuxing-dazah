"""add candidates table

Revision ID: 206e534a9ac5
Revises: 3b194df5596f
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '206e534a9ac5'
down_revision: Union[str, None] = '3b194df5596f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('candidates',
    sa.Column('name', sa.String(length=64), nullable=False, comment='姓名'),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('email', sa.String(length=128), nullable=True),
    sa.Column('position', sa.String(length=64), nullable=True, comment='应聘岗位'),
    sa.Column('department', sa.String(length=64), nullable=True),
    sa.Column('gender', sa.String(length=8), nullable=True),
    sa.Column('school', sa.String(length=128), nullable=True),
    sa.Column('education', sa.String(length=16), nullable=True),
    sa.Column('major', sa.String(length=64), nullable=True),
    sa.Column('graduation_date', sa.Date(), nullable=True),
    sa.Column('resume_url', sa.String(length=512), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='待筛选', nullable=False),
    sa.Column('recommendation_level', sa.String(length=8), nullable=True, comment='S/A/B/C'),
    sa.Column('match_report', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_candidates_status', 'candidates', ['status'], unique=False, schema='hr')
    op.create_index('ix_candidates_email', 'candidates', ['email'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_candidates_email', table_name='candidates', schema='hr')
    op.drop_index('ix_candidates_status', table_name='candidates', schema='hr')
    op.drop_table('candidates', schema='hr')
