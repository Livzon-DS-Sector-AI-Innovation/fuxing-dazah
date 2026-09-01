"""create warehouse module tables

Revision ID: 97645df4a45e
Revises: 4cb39e7a28c0
Create Date: 2026-09-01 11:07:47.619923
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '97645df4a45e'
down_revision: str | None = '4cb39e7a28c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # autogenerate 不会生成 CREATE SCHEMA，空库部署必须手动创建
    op.execute("CREATE SCHEMA IF NOT EXISTS warehouse")

    op.create_table('warehouse_locations',
    sa.Column('code', sa.String(length=50), nullable=False, comment='库位编码'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='库位名称'),
    sa.Column('location_type', sa.String(length=20), server_default='normal', nullable=False, comment='类型: normal常温/cold冷藏/danger危险品'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("location_type IN ('normal', 'cold', 'danger')", name='ck_warehouse_locations_type'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('uq_warehouse_locations_code', 'warehouse_locations', ['code'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('warehouse_materials',
    sa.Column('code', sa.String(length=50), nullable=False, comment='物料编码'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='物料名称'),
    sa.Column('category', sa.String(length=20), nullable=False, comment='分类: raw原料/auxiliary辅料/packaging包材/intermediate中间体/finished成品'),
    sa.Column('spec', sa.String(length=200), nullable=True, comment='规格型号'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='计量单位'),
    sa.Column('safety_stock', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False, comment='安全库存，低于该值提醒'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("category IN ('raw', 'auxiliary', 'packaging', 'intermediate', 'finished')", name='ck_warehouse_materials_category'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('uq_warehouse_materials_code', 'warehouse_materials', ['code'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('warehouse_movements',
    sa.Column('movement_no', sa.String(length=50), nullable=False, comment='单据编号'),
    sa.Column('direction', sa.String(length=20), nullable=False, comment='方向: inbound入库/outbound出库/adjust盘点调整'),
    sa.Column('source_type', sa.String(length=20), nullable=False, comment='来源: purchase采购/production生产/sale销售/return退料/stocktake盘点/other其他'),
    sa.Column('material_id', sa.Uuid(), nullable=False),
    sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
    sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='批次号，空串表示无批次'),
    sa.Column('quantity', sa.Numeric(precision=18, scale=4), nullable=False, comment='数量，恒为正'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='计量单位（冗余）'),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('location_code', sa.String(length=50), nullable=False, comment='库位编码（冗余）'),
    sa.Column('location_name', sa.String(length=200), nullable=False, comment='库位名称（冗余）'),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='业务发生时间'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("direction IN ('inbound', 'outbound', 'adjust')", name='ck_warehouse_movements_direction'),
    sa.CheckConstraint("source_type IN ('purchase', 'production', 'sale', 'return', 'stocktake', 'other')", name='ck_warehouse_movements_source_type'),
    sa.CheckConstraint('quantity > 0', name='ck_warehouse_movements_quantity_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('ix_warehouse_movements_material', 'warehouse_movements', ['material_id'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_movements_occurred', 'warehouse_movements', ['occurred_at'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_movements_no', 'warehouse_movements', ['movement_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('warehouse_stocks',
    sa.Column('material_id', sa.Uuid(), nullable=False),
    sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
    sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='批次号，空串表示无批次'),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('location_code', sa.String(length=50), nullable=False, comment='库位编码（冗余）'),
    sa.Column('location_name', sa.String(length=200), nullable=False, comment='库位名称（冗余）'),
    sa.Column('quantity', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False, comment='库存数量'),
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
    op.create_index('ix_warehouse_stocks_location', 'warehouse_stocks', ['location_id'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_stocks_material', 'warehouse_stocks', ['material_id'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_stocks_key', 'warehouse_stocks', ['material_id', 'batch_no', 'location_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('warehouse_stocktakes',
    sa.Column('stocktake_no', sa.String(length=50), nullable=False, comment='盘点单号'),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False, comment='状态: draft草稿/confirmed已确认'),
    sa.Column('scope_location_id', sa.Uuid(), nullable=True, comment='盘点范围库位，空表示全库'),
    sa.Column('scope_location_code', sa.String(length=50), nullable=True, comment='盘点范围库位编码（冗余）'),
    sa.Column('scope_location_name', sa.String(length=200), nullable=True, comment='盘点范围库位名称（冗余）'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='确认时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'confirmed')", name='ck_warehouse_stocktakes_status'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='warehouse'
    )
    op.create_index('uq_warehouse_stocktakes_no', 'warehouse_stocktakes', ['stocktake_no'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('warehouse_stocktake_items',
    sa.Column('stocktake_id', sa.Uuid(), nullable=False),
    sa.Column('material_id', sa.Uuid(), nullable=False),
    sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
    sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='批次号，空串表示无批次'),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('location_code', sa.String(length=50), nullable=False, comment='库位编码（冗余）'),
    sa.Column('location_name', sa.String(length=200), nullable=False, comment='库位名称（冗余）'),
    sa.Column('book_quantity', sa.Numeric(precision=18, scale=4), nullable=False, comment='账面数量快照'),
    sa.Column('counted_quantity', sa.Numeric(precision=18, scale=4), nullable=True, comment='实盘数量，空表示未盘'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
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
    op.create_index('ix_warehouse_stocktake_items_stocktake', 'warehouse_stocktake_items', ['stocktake_id'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_stocktake_items_key', 'warehouse_stocktake_items', ['stocktake_id', 'material_id', 'batch_no', 'location_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_warehouse_stocktake_items_key', table_name='warehouse_stocktake_items', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_warehouse_stocktake_items_stocktake', table_name='warehouse_stocktake_items', schema='warehouse')
    op.drop_table('warehouse_stocktake_items', schema='warehouse')
    op.drop_index('uq_warehouse_stocktakes_no', table_name='warehouse_stocktakes', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('warehouse_stocktakes', schema='warehouse')
    op.drop_index('uq_warehouse_stocks_key', table_name='warehouse_stocks', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_warehouse_stocks_material', table_name='warehouse_stocks', schema='warehouse')
    op.drop_index('ix_warehouse_stocks_location', table_name='warehouse_stocks', schema='warehouse')
    op.drop_table('warehouse_stocks', schema='warehouse')
    op.drop_index('uq_warehouse_movements_no', table_name='warehouse_movements', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_warehouse_movements_occurred', table_name='warehouse_movements', schema='warehouse')
    op.drop_index('ix_warehouse_movements_material', table_name='warehouse_movements', schema='warehouse')
    op.drop_table('warehouse_movements', schema='warehouse')
    op.drop_index('uq_warehouse_materials_code', table_name='warehouse_materials', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('warehouse_materials', schema='warehouse')
    op.drop_index('uq_warehouse_locations_code', table_name='warehouse_locations', schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('warehouse_locations', schema='warehouse')
    op.execute("DROP SCHEMA IF EXISTS warehouse")
