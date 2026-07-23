"""add_transfer_records

Revision ID: 2afdfae4653f
Revises: 86ca84a3662e
Create Date: 2026-07-19 22:14:55.619571
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '2afdfae4653f'
down_revision: Union[str, None] = '86ca84a3662e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('transfer_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工ID'),
        sa.Column('transfer_type', sa.String(length=16), nullable=False, server_default='调动', comment='异动类型: 调动/晋升/降职/转岗'),
        sa.Column('from_department', sa.String(length=64), nullable=True, comment='原部门'),
        sa.Column('to_department', sa.String(length=64), nullable=True, comment='新部门'),
        sa.Column('from_position', sa.String(length=64), nullable=True, comment='原岗位'),
        sa.Column('to_position', sa.String(length=64), nullable=True, comment='新岗位'),
        sa.Column('effective_date', sa.Date(), nullable=False, comment='生效日期'),
        sa.Column('reason', sa.String(length=256), nullable=True, comment='调动原因'),
        sa.Column('approval_id', sa.String(length=64), nullable=True, comment='审批单号'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_transfer_records_employee_id', 'transfer_records', ['employee_id'], schema='hr')
    op.create_index('ix_transfer_records_effective_date', 'transfer_records', ['effective_date'], schema='hr')


def downgrade() -> None:
    op.drop_table('transfer_records', schema='hr')
