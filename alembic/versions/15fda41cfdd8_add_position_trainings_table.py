"""add position_trainings table

Revision ID: 15fda41cfdd8
Revises: 14fda41cfdd7
Create Date: 2026-07-10 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '15fda41cfdd8'
down_revision: Union[str, None] = '14fda41cfdd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('position_trainings',
        sa.Column('position_name', sa.String(128), nullable=False, comment='岗位名称'),
        sa.Column('department', sa.String(128), nullable=False, comment='所属部门'),
        sa.Column('variety', sa.String(64), nullable=True, comment='品种'),
        sa.Column('training_category', sa.String(256), nullable=False, comment='培训类别'),
        sa.Column('trainer', sa.String(64), nullable=True, comment='培训师'),
        sa.Column('training_method', sa.String(64), nullable=True, comment='培训方式'),
        sa.Column('sop_number', sa.String(64), nullable=True, comment='SOP编号'),
        sa.Column('file_name', sa.String(512), nullable=True, comment='文件名称'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_pt_position', 'position_trainings', ['position_name'], schema='hr')
    op.create_index('ix_pt_department', 'position_trainings', ['department'], schema='hr')


def downgrade() -> None:
    op.drop_table('position_trainings', schema='hr')
