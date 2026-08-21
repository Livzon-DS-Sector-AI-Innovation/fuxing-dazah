"""add_sop_training_master

Revision ID: 0dd6e73589c0
Revises: 9b36fb027df9
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0dd6e73589c0'
down_revision: Union[str, None] = '9b36fb027df9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(
        'sop_training_masters',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('department', sa.String(128), nullable=False, comment='发起部门'),
        sa.Column('sop_ids', sa.Text(), nullable=True, comment='关联SOP条目ID，JSON数组'),
        sa.Column('trainer', sa.String(64), nullable=True, comment='培训师'),
        sa.Column('status', sa.String(16), nullable=False, server_default='草稿', comment='草稿/已提交/已转训'),
        sa.Column('created_by', sa.String(64), nullable=True, comment='创建人'),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_sop_master_department', 'sop_training_masters', ['department'], schema='hr')
    op.create_index('ix_sop_master_status', 'sop_training_masters', ['status'], schema='hr')


def downgrade() -> None:
    op.drop_table('sop_training_masters', schema='hr')
