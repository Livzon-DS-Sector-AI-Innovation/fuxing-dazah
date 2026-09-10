"""add chemical inventory snapshots

周趋势分析用：chemical_inventory_snapshots 快照表。

Revision ID: 1f7df0201945
Revises: 38387c4de6c6
Create Date: 2026-08-25 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1f7df0201945'
down_revision: str | None = '38387c4de6c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table('chemical_inventory_snapshots',
    sa.Column('snapshot_date', sa.Date(), nullable=False, comment='快照日期'),
    sa.Column('department', sa.String(length=32), nullable=False, comment='部门'),
    sa.Column('storage_location', sa.String(length=128), nullable=True, comment='存放部位'),
    sa.Column('material_name', sa.String(length=128), nullable=False, comment='物料名称'),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=True, comment='库存数量'),
    sa.Column('unit', sa.String(length=16), nullable=True, comment='单位'),
    sa.Column('total_quantity_t', sa.Numeric(precision=14, scale=4), nullable=True, comment='现场物料总量(T)'),
    sa.Column('risk_flag', sa.String(length=16), server_default='normal', nullable=False, comment='风险标记(正常/预警)'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_cisnap_date_dept', 'chemical_inventory_snapshots', ['snapshot_date', 'department'], unique=False, schema='safety')
    op.create_index('uq_cisnap_key', 'chemical_inventory_snapshots', ['snapshot_date', 'department', 'storage_location', 'material_name'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_cisnap_key', table_name='chemical_inventory_snapshots', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('idx_cisnap_date_dept', table_name='chemical_inventory_snapshots', schema='safety')
    op.drop_table('chemical_inventory_snapshots', schema='safety')
