"""warehouse stock daily snapshots

库存日快照表：按物料聚合的每日库存总量，驾驶舱环比/趋势的数据底座。
同日重跑幂等覆盖（部分唯一索引 snapshot_date + material_id where is_deleted = false）。

Revision ID: b3e8c2d1f4a6
Revises: c7c4b6b6a8a4
Create Date: 2026-09-15
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e8c2d1f4a6'
down_revision: str | None = 'c7c4b6b6a8a4'
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
    # 快照表落在既有 warehouse schema；空库/新环境兜底建 schema
    op.execute('CREATE SCHEMA IF NOT EXISTS warehouse')

    op.create_table('stock_daily_snapshots',
        sa.Column('snapshot_date', sa.Date(), nullable=False, comment='快照业务日'),
        sa.Column('material_id', sa.Uuid(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
        sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
        sa.Column('total_quantity', sa.Numeric(18, 4), server_default='0', nullable=False, comment='当日库存总量（跨批次/库位求和）'),
        sa.Column('stock_rows', sa.Integer(), server_default='0', nullable=False, comment='当日库存行数（批次×库位）'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_stock_daily_snapshots_date', 'stock_daily_snapshots', ['snapshot_date'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_stock_daily_snapshots_key', 'stock_daily_snapshots', ['snapshot_date', 'material_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_warehouse_stock_daily_snapshots_key', table_name='stock_daily_snapshots', schema='warehouse')
    op.drop_index('ix_warehouse_stock_daily_snapshots_date', table_name='stock_daily_snapshots', schema='warehouse')
    op.drop_table('stock_daily_snapshots', schema='warehouse')
