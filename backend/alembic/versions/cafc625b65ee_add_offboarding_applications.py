"""add_offboarding_applications

Revision ID: cafc625b65ee
Revises: cebe04fbaf3e
Create Date: 2026-07-21 08:40:08.417121
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'cafc625b65ee'
down_revision: Union[str, None] = 'cebe04fbaf3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('offboarding_applications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('employee_id', sa.String(length=64), nullable=False, comment='员工ID(UUID)'),
        sa.Column('employee_number', sa.String(length=32), nullable=False, comment='工号'),
        sa.Column('name', sa.String(length=64), nullable=False, comment='姓名'),
        sa.Column('department', sa.String(length=64), nullable=False, comment='部门'),
        sa.Column('position', sa.String(length=64), nullable=False, comment='岗位'),
        sa.Column('offboarding_date', sa.Date(), nullable=False, comment='离职日期'),
        sa.Column('offboarding_type', sa.String(length=16), nullable=False, server_default='辞职', comment='离职类型'),
        sa.Column('reason', sa.String(length=512), nullable=True, comment='离职原因'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='待审批', comment='状态'),
        sa.Column('approved_at', sa.Date(), nullable=True, comment='审批日期'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_offboarding_applications_status', 'offboarding_applications', ['status'], schema='hr')


def downgrade() -> None:
    op.drop_table('offboarding_applications', schema='hr')
