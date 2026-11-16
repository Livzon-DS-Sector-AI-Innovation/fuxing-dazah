"""hr_headcount_plans

部门定编表：随员工档案同步从飞书「定编数」表拉取

Revision ID: a3f8c1d60b42
Revises: 9ce7cc860598
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c1d60b42'
down_revision: Union[str, None] = '9ce7cc860598'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'headcount_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('department', sa.String(64), nullable=False, comment='部门名称（与定编表一致）'),
        sa.Column('department_quota', sa.Integer(), server_default='0', nullable=False, comment='部门定编人数'),
        sa.Column('position_detail', sa.Text(), server_default='', nullable=False, comment='岗位明细原文（如「经理×1; 副经理×1」）'),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
        sa.Column('source_current_count', sa.Integer(), nullable=True, comment='飞书表手填「现有人数」（仅参考，不做计算口径）'),
        sa.Column('feishu_record_id', sa.String(32), nullable=True, comment='飞书多维表格 record_id'),
        sa.Column('feishu_synced_at', sa.Date(), nullable=True, comment='上次飞书同步时间'),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('department', name='uq_headcount_plans_department'),
        schema='hr',
    )
    op.create_index('ix_headcount_plans_record_id', 'headcount_plans', ['feishu_record_id'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_headcount_plans_record_id', table_name='headcount_plans', schema='hr')
    op.drop_table('headcount_plans', schema='hr')
