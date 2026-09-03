"""warehouse agent tables

Revision ID: 7bf849ceb7e2
Revises: 97645df4a45e
Create Date: 2026-09-03 15:47:48.434960
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7bf849ceb7e2'
down_revision: Union[str, None] = '97645df4a45e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('warehouse_agent_audit',
    sa.Column('tool_name', sa.String(length=60), nullable=False, comment='工具名'),
    sa.Column('args_summary', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='参数摘要（截断）'),
    sa.Column('result_status', sa.String(length=30), nullable=False, comment='ok/error/denied'),
    sa.Column('error_code', sa.String(length=30), nullable=True, comment='错误码分类（如 1254062）'),
    sa.Column('duration_ms', sa.Numeric(precision=10), server_default='0', nullable=False, comment='耗时毫秒'),
    sa.Column('session_id', sa.Uuid(), nullable=True, comment='关联会话'),
    sa.Column('draft_id', sa.Uuid(), nullable=True, comment='关联草稿'),
    sa.Column('plan_id', sa.Uuid(), nullable=True, comment='关联计划'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('ix_warehouse_agent_audit_draft', 'warehouse_agent_audit', ['draft_id'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_agent_audit_tool', 'warehouse_agent_audit', ['tool_name'], unique=False, schema='warehouse')
    op.create_table('warehouse_agent_drafts',
    sa.Column('draft_no', sa.String(length=50), nullable=False, comment='草稿编号'),
    sa.Column('scene', sa.String(length=50), nullable=False, comment='场景: receipt/gmp_outbound/finished_outbound'),
    sa.Column('source_image', sa.String(length=200), nullable=True, comment='来源图片 file token'),
    sa.Column('recognized', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='模型原始识别结果'),
    sa.Column('aligned', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='主数据对齐后字段+置信度'),
    sa.Column('status', sa.String(length=30), server_default='created', nullable=False, comment='created/aligned/pending_confirm/confirmed/submitted/expired/cancelled'),
    sa.Column('target_base', sa.String(length=60), nullable=True, comment='目标 Base token'),
    sa.Column('target_table', sa.String(length=60), nullable=True, comment='目标表 table_id'),
    sa.Column('target_record_id', sa.String(length=60), nullable=True, comment='写入成功后回填的 record_id'),
    sa.Column('created_by_open_id', sa.String(length=60), nullable=True, comment='发起人飞书 open_id'),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True, comment='草稿过期时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('ix_warehouse_agent_drafts_status', 'warehouse_agent_drafts', ['status'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_agent_drafts_no', 'warehouse_agent_drafts', ['draft_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('warehouse_agent_memories',
    sa.Column('scope', sa.String(length=20), nullable=False, comment='user/global'),
    sa.Column('owner_open_id', sa.String(length=60), nullable=True, comment='用户 open_id（global 时为空）'),
    sa.Column('memory_type', sa.String(length=30), nullable=False, comment='preference/convention/alias'),
    sa.Column('content', sa.Text(), nullable=False, comment='记忆内容'),
    sa.Column('hit_count', sa.Numeric(precision=10), server_default='0', nullable=False, comment='注入命中计数（淘汰用）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('ix_warehouse_agent_memories_scope', 'warehouse_agent_memories', ['scope', 'owner_open_id'], unique=False, schema='warehouse')
    op.create_table('warehouse_agent_plans',
    sa.Column('plan_no', sa.String(length=50), nullable=False, comment='计划编号'),
    sa.Column('title', sa.String(length=200), nullable=False, comment='任务标题'),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False, comment='[{no,desc,status,note}]'),
    sa.Column('status', sa.String(length=30), server_default='active', nullable=False, comment='active/done/abandoned'),
    sa.Column('session_id', sa.Uuid(), nullable=True, comment='所属会话'),
    sa.Column('created_by_open_id', sa.String(length=60), nullable=True, comment='发起人飞书 open_id'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('uq_warehouse_agent_plans_no', 'warehouse_agent_plans', ['plan_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('warehouse_agent_sessions',
    sa.Column('chat_id', sa.String(length=60), nullable=False, comment='飞书 chat_id（私聊为 p2p 标识）'),
    sa.Column('user_open_id', sa.String(length=60), nullable=False, comment='用户飞书 open_id'),
    sa.Column('history', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='最近消息与轮次摘要'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('uq_warehouse_agent_sessions_key', 'warehouse_agent_sessions', ['chat_id', 'user_open_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))



def downgrade() -> None:
    op.drop_index('uq_warehouse_agent_sessions_key', table_name='warehouse_agent_sessions', schema='warehouse')
    op.drop_table('warehouse_agent_sessions', schema='warehouse')
    op.drop_index('uq_warehouse_agent_plans_no', table_name='warehouse_agent_plans', schema='warehouse')
    op.drop_table('warehouse_agent_plans', schema='warehouse')
    op.drop_index('ix_warehouse_agent_memories_scope', table_name='warehouse_agent_memories', schema='warehouse')
    op.drop_table('warehouse_agent_memories', schema='warehouse')
    op.drop_index('uq_warehouse_agent_drafts_no', table_name='warehouse_agent_drafts', schema='warehouse')
    op.drop_index('ix_warehouse_agent_drafts_status', table_name='warehouse_agent_drafts', schema='warehouse')
    op.drop_table('warehouse_agent_drafts', schema='warehouse')
    op.drop_index('ix_warehouse_agent_audit_draft', table_name='warehouse_agent_audit', schema='warehouse')
    op.drop_index('ix_warehouse_agent_audit_tool', table_name='warehouse_agent_audit', schema='warehouse')
    op.drop_table('warehouse_agent_audit', schema='warehouse')
