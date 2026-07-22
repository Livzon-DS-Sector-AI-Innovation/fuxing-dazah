"""add_onboarding_applications

Revision ID: ff36e7e1856e
Revises: 750937375a35
Create Date: 2026-07-20 00:08:52.166610
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'ff36e7e1856e'
down_revision: Union[str, None] = '750937375a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('onboarding_applications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False, comment='姓名'),
        sa.Column('employee_number', sa.String(length=32), nullable=False, comment='工号'),
        sa.Column('gender', sa.String(length=8), nullable=True, comment='性别'),
        sa.Column('department', sa.String(length=64), nullable=False, comment='部门'),
        sa.Column('position', sa.String(length=64), nullable=False, comment='岗位'),
        sa.Column('hire_date', sa.Date(), nullable=False, comment='入职日期'),
        sa.Column('education', sa.String(length=16), nullable=True, comment='学历'),
        sa.Column('school', sa.String(length=128), nullable=True, comment='毕业院校'),
        sa.Column('major', sa.String(length=64), nullable=True, comment='专业'),
        sa.Column('phone', sa.String(length=32), nullable=True, comment='手机号'),
        sa.Column('email', sa.String(length=128), nullable=True, comment='邮箱'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='待审批', comment='状态: 待审批/已通过/已拒绝'),
        sa.Column('approver_id', sa.String(length=64), nullable=True, comment='审批人ID'),
        sa.Column('approved_at', sa.Date(), nullable=True, comment='审批日期'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_onboarding_applications_status', 'onboarding_applications', ['status'], schema='hr')


def downgrade() -> None:
    op.drop_table('onboarding_applications', schema='hr')
