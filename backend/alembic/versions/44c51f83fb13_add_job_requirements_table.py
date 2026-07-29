"""add job requirements table

Revision ID: 44c51f83fb13
Revises: 206e534a9ac5
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '44c51f83fb13'
down_revision: Union[str, None] = '206e534a9ac5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('job_requirements',
    sa.Column('position_name', sa.String(length=64), nullable=False, comment='岗位名称'),
    sa.Column('department', sa.String(length=64), nullable=False, comment='需求部门'),
    sa.Column('headcount', sa.Integer(), server_default='1', nullable=False, comment='招聘人数'),
    sa.Column('hired_count', sa.Integer(), server_default='0', nullable=False, comment='已入职人数'),
    sa.Column('requirements', sa.Text(), nullable=True, comment='岗位要求描述'),
    sa.Column('status', sa.String(length=16), server_default='招聘中', nullable=False, comment='招聘中/已关闭'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_job_req_department', 'job_requirements', ['department'], unique=False, schema='hr')
    op.create_index('ix_job_req_status', 'job_requirements', ['status'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_job_req_status', table_name='job_requirements', schema='hr')
    op.drop_index('ix_job_req_department', table_name='job_requirements', schema='hr')
    op.drop_table('job_requirements', schema='hr')
