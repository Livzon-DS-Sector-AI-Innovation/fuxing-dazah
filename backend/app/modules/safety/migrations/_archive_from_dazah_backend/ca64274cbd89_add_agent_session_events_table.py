"""add agent_session_events table

Revision ID: ca64274cbd89
Revises: 995c231d41c7
Create Date: 2026-08-19 16:12:54.287518

手工清理：autogenerate 混入了大量其它模块无关变更（permission 建表、safety 业务表
误 drop/alter 等），只保留本表 ``agent_session_events`` 的 DDL，避免破坏现有数据与 schema。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ca64274cbd89'
down_revision: Union[str, None] = '995c231d41c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # safety schema 已存在（baseline 已建），无需 CREATE SCHEMA
    op.create_table('agent_session_events',
    sa.Column('session_id', sa.Uuid(), nullable=False, comment='关联 agent_sessions.id（命名约定，无 FK 约束）'),
    sa.Column('seq', sa.Integer(), nullable=False, comment='per session 单调递增序列号（从 1 起，不复用）'),
    sa.Column('event_type', sa.String(length=32), nullable=False, comment='user_message | assistant_message | tool_call | tool_result | approval_requested | approval_resolved | memory_write | turn_end'),
    sa.Column('payload', sa.JSON(), nullable=False, comment='事件载荷（见 backend-design §2.1.2 payload schema）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    # 唯一索引 (session_id, seq)：事件源 seq 单调递增防护（软删后禁止复用 seq）
    op.create_index('ix_agent_session_events_session_seq', 'agent_session_events',
                    ['session_id', 'seq'], unique=True, schema='safety')
    op.create_index('ix_agent_session_events_session_created', 'agent_session_events',
                    ['session_id', 'created_at'], unique=False, schema='safety')
    op.create_index('ix_agent_session_events_type', 'agent_session_events',
                    ['event_type'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('ix_agent_session_events_type', table_name='agent_session_events', schema='safety')
    op.drop_index('ix_agent_session_events_session_created', table_name='agent_session_events', schema='safety')
    op.drop_index('ix_agent_session_events_session_seq', table_name='agent_session_events', schema='safety')
    op.drop_table('agent_session_events', schema='safety')