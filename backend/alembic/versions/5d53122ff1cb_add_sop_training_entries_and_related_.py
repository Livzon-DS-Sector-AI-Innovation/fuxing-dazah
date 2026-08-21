"""add_sop_training_entries_and_related_departments

Revision ID: 5d53122ff1cb
Revises: a4efff3b401e
Create Date: 2026-08-13 12:03:41.547108

统筹总表增加关联部门字段；新增 SOP 培训二级表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d53122ff1cb'
down_revision: Union[str, None] = 'a4efff3b401e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 统筹总表：关联相关部门（JSON 数组）
    op.add_column(
        'sop_training_masters',
        sa.Column('related_departments', sa.Text(), nullable=True, comment='关联相关部门（二级表按此自动生成），JSON 数组'),
        schema='hr',
    )

    # 二级表
    op.create_table(
        'sop_training_entries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('master_id', sa.String(36), nullable=True, comment='统筹总表 ID'),
        sa.Column('department', sa.String(128), nullable=False, comment='培训部门'),
        sa.Column('sop_ids', sa.Text(), nullable=True, comment='关联 SOP 条目 ID，JSON 数组'),
        sa.Column('trainer', sa.String(64), nullable=True, comment='培训师（转培训时自动带出一级培训师）'),
        sa.Column('status', sa.String(16), nullable=False, server_default='待转训', comment='待转训/已转训'),
        sa.Column('classification', sa.String(64), nullable=True, comment='自定义分类（对应部门员工标签）'),
        sa.Column('personnel', sa.Text(), nullable=True, comment='分类人员，JSON 数组'),
        sa.Column('transferred_by', sa.String(64), nullable=True, comment='转培训操作人'),
        sa.Column('transferred_at', sa.DateTime(timezone=True), nullable=True, comment='转培训时间'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_sop_entry_master', 'sop_training_entries', ['master_id'], schema='hr')
    op.create_index('ix_sop_entry_department', 'sop_training_entries', ['department'], schema='hr')
    op.create_index('ix_sop_entry_status', 'sop_training_entries', ['status'], schema='hr')


def downgrade() -> None:
    op.drop_table('sop_training_entries', schema='hr')
    op.drop_column('sop_training_masters', 'related_departments', schema='hr')
