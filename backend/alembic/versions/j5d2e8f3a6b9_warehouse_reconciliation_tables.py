"""warehouse reconciliation tables (Phase C stage 2)

对账中心数据底座：对账运行记录 + 差异明细（仅落非 match 行）。

Revision ID: j5d2e8f3a6b9
Revises: i4c9d7e6f5a2
Create Date: 2026-09-16
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'j5d2e8f3a6b9'
down_revision: str | None = 'i4c9d7e6f5a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
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
        sa.ForeignKeyConstraint(['run_id'], ['warehouse.sync_check_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS warehouse')

    op.create_table('sync_check_runs',
        sa.Column('status', sa.String(16), server_default='running', nullable=False, comment='running/completed/failed'),
        sa.Column('total_local', sa.Integer(), server_default='0', nullable=False, comment='本地总行数'),
        sa.Column('total_feishu', sa.Integer(), server_default='0', nullable=False, comment='飞书总行数'),
        sa.Column('cnt_match', sa.Integer(), server_default='0', nullable=False, comment='一致数'),
        sa.Column('cnt_missing_in_feishu', sa.Integer(), server_default='0', nullable=False, comment='飞书缺失数'),
        sa.Column('cnt_mismatch', sa.Integer(), server_default='0', nullable=False, comment='数量不一致数'),
        sa.Column('cnt_missing_local', sa.Integer(), server_default='0', nullable=False, comment='本地缺失数'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='失败原因'),
        sa.Column('duration_ms', sa.Integer(), server_default='0', nullable=False, comment='耗时毫秒'),
        *_base_columns(),
        sa.PrimaryKeyConstraint('id'),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_sync_check_runs_status', 'sync_check_runs', ['status'], schema='warehouse')

    op.create_table('sync_check_results',
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, comment='missing_in_feishu/mismatch/missing_local'),
        sa.Column('material_code', sa.String(50), nullable=False, comment='物料编码'),
        sa.Column('material_name', sa.String(200), nullable=False, comment='物料名称'),
        sa.Column('batch_no', sa.String(100), server_default='', nullable=False, comment='批次号'),
        sa.Column('local_qty', sa.Numeric(18, 4), nullable=True, comment='本地数量'),
        sa.Column('feishu_qty', sa.Numeric(18, 4), nullable=True, comment='飞书数量'),
        sa.Column('feishu_record_id', sa.String(64), nullable=True, comment='飞书记录 ID'),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='差异详情'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_sync_check_results_run', 'sync_check_results', ['run_id'], schema='warehouse')
    op.create_index('ix_warehouse_sync_check_results_status', 'sync_check_results', ['status'], schema='warehouse')


def downgrade() -> None:
    op.drop_index('ix_warehouse_sync_check_results_status', table_name='sync_check_results', schema='warehouse')
    op.drop_index('ix_warehouse_sync_check_results_run', table_name='sync_check_results', schema='warehouse')
    op.drop_table('sync_check_results', schema='warehouse')
    op.drop_index('ix_warehouse_sync_check_runs_status', table_name='sync_check_runs', schema='warehouse')
    op.drop_table('sync_check_runs', schema='warehouse')
