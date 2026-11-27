"""add employee info collection table

Revision ID: d8f4b2c61e90
Revises: e7c5b1f93a2d
Create Date: 2026-11-13 10:00:00.000000

员工档案：新员工信息收集任务表（飞书机器人表单卡片 → HR 审核合并）。
同一员工同时只允许一个进行中任务（sent/submitted 部分唯一索引）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8f4b2c61e90'
down_revision: Union[str, None] = 'e7c5b1f93a2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'employee_info_collections'
_SCHEMA = 'hr'


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(_TABLE,
    sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID'),
    sa.Column('open_id', sa.String(length=64), nullable=False, comment='卡片接收人飞书open_id'),
    sa.Column('card_message_id', sa.String(length=64), nullable=True, comment='表单卡片消息ID'),
    sa.Column('status', sa.String(length=16), nullable=False, server_default='sent',
              comment='sent已发待填/submitted已提交待审/approved已采纳/rejected已驳回'),
    sa.Column('form_data', sa.JSON(), nullable=True, comment='员工提交的字段值 {orm字段: 值}'),
    sa.Column('reject_reason', sa.String(length=256), nullable=True, comment='驳回原因'),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True, comment='员工提交时间'),
    sa.Column('reviewed_by', sa.String(length=64), nullable=True, comment='审核人'),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True, comment='审核时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], [f'{_SCHEMA}.employees.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema=_SCHEMA
    )
    # 同一员工同时只允许一个进行中任务
    op.create_index(
        'uq_eic_employee_active', _TABLE, ['employee_id'], unique=True, schema=_SCHEMA,
        postgresql_where=sa.text("status IN ('sent', 'submitted') AND is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index('uq_eic_employee_active', table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
