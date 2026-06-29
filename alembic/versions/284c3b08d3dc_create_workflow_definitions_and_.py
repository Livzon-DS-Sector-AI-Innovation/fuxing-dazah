"""create workflow_definitions and workflow_runs tables

Revision ID: 284c3b08d3dc
Revises: 2af364a150a5
Create Date: 2026-06-29 12:26:50.015589
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '284c3b08d3dc'
down_revision: Union[str, None] = '2af364a150a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 安全模块 workflow 引擎 - 工作流定义表
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table('workflow_definitions',
        sa.Column('name', sa.String(length=128), nullable=False, comment='工作流名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='描述'),
        sa.Column('module_code', sa.String(length=64), nullable=False, comment='模块代码'),
        sa.Column('graph', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"), comment='graphon 兼容的 graph JSON'),
        sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='是否启用'),
        sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='版本号'),
        sa.Column('created_by', sa.String(length=64), nullable=True, comment='创建人'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=True, comment='更新人'),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False, comment='软删除'),
        sa.PrimaryKeyConstraint('id'),
        schema='safety'
    )
    op.create_index(
        'ix_workflow_definitions_module_code',
        'workflow_definitions', ['module_code'],
        unique=True, schema='safety',
        postgresql_where=sa.text('is_deleted = false'),
    )

    # 安全模块 workflow 引擎 - 运行记录表
    op.create_table('workflow_runs',
        sa.Column('workflow_id', sa.UUID(), nullable=False, comment='关联 workflow_definitions.id'),
        sa.Column('inputs', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"), comment='输入变量'),
        sa.Column('outputs', sa.JSON(), nullable=True, comment='最终输出'),
        sa.Column('node_results', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"), comment='各节点执行结果'),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False, comment='执行状态'),
        sa.Column('total_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='Token 消耗总计'),
        sa.Column('total_steps', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='执行步骤数'),
        sa.Column('elapsed_time', sa.Float(), nullable=True, comment='执行耗时(秒)'),
        sa.Column('entity_type', sa.String(length=50), nullable=True, comment='关联业务实体类型'),
        sa.Column('entity_id', sa.String(length=64), nullable=True, comment='关联业务实体 ID'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='失败原因'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True, comment='开始时间'),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True, comment='完成时间'),
        sa.Column('created_by', sa.String(length=64), nullable=True, comment='创建人'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=True, comment='更新人'),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False, comment='软删除'),
        sa.PrimaryKeyConstraint('id'),
        schema='safety'
    )


def downgrade() -> None:
    op.drop_table('workflow_runs', schema='safety')
    op.drop_table('workflow_definitions', schema='safety')
