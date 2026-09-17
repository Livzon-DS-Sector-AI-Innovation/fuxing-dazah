"""warehouse stocks add status + stock_status_logs

库存状态机：warehouse_stocks 加 status 列（normal/quarantine/frozen）+
warehouse_stock_status_logs 流转日志表。

Revision ID: l7f3a9b5c8d2
Revises: k6e9f1a3b7c4
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'l7f3a9b5c8d2'
down_revision: str | None = 'k6e9f1a3b7c4'
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
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.add_column('warehouse_stocks',
        sa.Column('status', sa.String(length=16), server_default='normal', nullable=False,
                  comment='状态: normal/quarantine/frozen'), schema='warehouse')

    op.create_table('stock_status_logs',
        sa.Column('stock_id', sa.Uuid(), nullable=False, comment='关联库存行'),
        sa.Column('old_status', sa.String(length=16), nullable=True, comment='变更前状态'),
        sa.Column('new_status', sa.String(length=16), nullable=False, comment='变更后状态'),
        sa.Column('reason', sa.Text(), nullable=True, comment='变更原因'),
        sa.Column('operator_id', sa.Uuid(), nullable=True, comment='操作人'),
        *_base_columns(), *_base_fks(),
        sa.ForeignKeyConstraint(['stock_id'], ['warehouse.warehouse_stocks.id']),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_stock_status_logs_stock', 'stock_status_logs', ['stock_id'], schema='warehouse')


def downgrade() -> None:
    op.drop_index('ix_warehouse_stock_status_logs_stock', table_name='stock_status_logs', schema='warehouse')
    op.drop_table('stock_status_logs', schema='warehouse')
    op.drop_column('warehouse_stocks', 'status', schema='warehouse')
