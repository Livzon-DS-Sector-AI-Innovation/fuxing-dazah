"""warehouse confirm gate tables

通用业务确认门（V3.0 分期A Ticket 05）：确认单 + 确认单审计 2 张表。
全部为确认/审计数据，无业务权威表（2B：权威在 Base）。

Revision ID: b8d4f2a6c1e9
Revises: a7c3e9f5b2d8
Create Date: 2026-09-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d4f2a6c1e9'
down_revision: str | None = 'a7c3e9f5b2d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    """BaseModel 公共列（与 app/shared/base_model.py 对齐）。"""
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.create_table('confirm_requests',
        sa.Column('request_no', sa.String(length=64), nullable=False, comment='确认单号 CR-yyyymmddHHMMSS-XXXXXX'),
        sa.Column('business_type', sa.String(length=64), nullable=False, comment='业务类型（如 unqualified_disposition）'),
        sa.Column('title', sa.String(length=128), nullable=False, comment='卡片标题'),
        sa.Column('summary', sa.Text(), nullable=False, comment='卡片正文（markdown，含清单摘要）'),
        sa.Column('ref_table', sa.String(length=64), nullable=False, comment='回写目标 Base 表 key'),
        sa.Column('ref_record_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='回写目标 record_id 列表'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='业务快照（审计/回执渲染用）'),
        sa.Column('target', sa.String(length=64), nullable=False, comment='确认卡投递目标（群 chat_id / 个人 open_id）'),
        sa.Column('writeback', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='回写字段映射 {Base字段名: 值}'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='pending/confirmed/cancelled/expired/failed'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='过期时间（默认 24h）'),
        sa.Column('confirmed_by', sa.String(length=64), nullable=True, comment='确认操作人 open_id'),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='确认时间'),
        sa.Column('resend_count', sa.Integer(), server_default='0', nullable=False, comment='重发次数'),
        sa.Column('card_message_id', sa.String(length=64), nullable=True, comment='确认卡 message_id（PATCH 原卡用）'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_confirm_requests_business_status', 'confirm_requests', ['business_type', 'status'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_confirm_requests_status_created', 'confirm_requests', ['status', 'created_at'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_confirm_requests_no', 'confirm_requests', ['request_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('confirm_request_audits',
        sa.Column('request_no', sa.String(length=64), nullable=False, comment='确认单号'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: create/confirm/cancel/expire/resend/writeback_ok/writeback_failed'),
        sa.Column('operator_open_id', sa.String(length=64), nullable=True, comment='操作人 open_id（系统动作为空）'),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='补充明细（回写条数/失败原因等）'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_confirm_request_audits_no_created', 'confirm_request_audits', ['request_no', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_confirm_request_audits_created', 'confirm_request_audits', ['created_at'], unique=False, schema='warehouse')


def downgrade() -> None:
    for table in ('confirm_request_audits', 'confirm_requests'):
        op.drop_table(table, schema='warehouse')
