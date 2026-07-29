"""add planning tables and extend batch model

Revision ID: 3f5f8e594160
Revises: c9fffc9a39a5
Create Date: 2026-07-23 11:38:12.566203
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f5f8e594160'
down_revision: Union[str, None] = 'c9fffc9a39a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")

    # --- new planning tables ---
    op.create_table('demands',
    sa.Column('demand_no', sa.String(length=30), nullable=False, comment='需求编号'),
    sa.Column('source_type', sa.String(length=20), nullable=False, comment='manual/sales_order/forecast/internal'),
    sa.Column('source_ref', sa.String(length=100), nullable=True, comment='外部来源引用号'),
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='产品'),
    sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名快照'),
    sa.Column('demanded_quantity', sa.Float(), nullable=False, comment='原始需求量'),
    sa.Column('allocated_quantity', sa.Float(), nullable=False, comment='已分配量'),
    sa.Column('fulfilled_quantity', sa.Float(), nullable=False, comment='已完成量'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='单位'),
    sa.Column('demand_date', sa.Date(), nullable=False, comment='需求日期'),
    sa.Column('priority', sa.String(length=10), nullable=False, comment='urgent/high/medium/low'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='pending/confirmed/partial/fulfilled/closed/cancelled'),
    sa.Column('customer_name', sa.String(length=100), nullable=True, comment='客户名称'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("source_type IN ('manual', 'sales_order', 'forecast', 'internal')", name='ck_production_demands_source_type'),
    sa.CheckConstraint("status IN ('pending', 'confirmed', 'partial', 'fulfilled', 'closed', 'cancelled')", name='ck_production_demands_status'),
    sa.CheckConstraint("priority IN ('urgent', 'high', 'medium', 'low')", name='ck_production_demands_priority'),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_demands_no', 'demands', ['demand_no'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('plan_orders',
    sa.Column('order_no', sa.String(length=30), nullable=False, comment='计划单号'),
    sa.Column('title', sa.String(length=200), nullable=False, comment='计划标题'),
    sa.Column('plan_version', sa.Integer(), nullable=False, comment='版本号'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='draft/confirmed/released/completed/closed'),
    sa.Column('scheduled_start', sa.Date(), nullable=True, comment='计划开始日期'),
    sa.Column('scheduled_end', sa.Date(), nullable=True, comment='计划结束日期'),
    sa.Column('priority', sa.String(length=10), nullable=False, comment='urgent/high/medium/low'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'confirmed', 'released', 'completed', 'closed')", name='ck_production_plan_orders_status'),
    sa.CheckConstraint("priority IN ('urgent', 'high', 'medium', 'low')", name='ck_production_plan_orders_priority'),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_plan_orders_no', 'plan_orders', ['order_no'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('plan_items',
    sa.Column('plan_order_id', sa.Uuid(), nullable=False, comment='所属计划单'),
    sa.Column('item_no', sa.Integer(), nullable=False, comment='计划单内序号'),
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='产品'),
    sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名快照'),
    sa.Column('route_id', sa.Uuid(), nullable=True, comment='工艺路线'),
    sa.Column('equipment_id', sa.String(length=100), nullable=True, comment='目标设备/产线'),
    sa.Column('planned_quantity', sa.Float(), nullable=False, comment='计划产量'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='单位'),
    sa.Column('planned_start', sa.DateTime(timezone=True), nullable=True, comment='计划开始时间'),
    sa.Column('planned_end', sa.DateTime(timezone=True), nullable=True, comment='计划结束时间'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='draft/scheduled/allocated/in_progress/completed/cancelled'),
    sa.Column('priority', sa.String(length=10), nullable=False, comment='urgent/high/medium/low'),
    sa.Column('sort_order', sa.Integer(), nullable=False, comment='排程序号'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'scheduled', 'allocated', 'in_progress', 'completed', 'cancelled')", name='ck_production_plan_items_status'),
    sa.CheckConstraint("priority IN ('urgent', 'high', 'medium', 'low')", name='ck_production_plan_items_priority'),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_plan_items_no', 'plan_items', ['plan_order_id', 'item_no'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_production_plan_items_equipment_time', 'plan_items', ['equipment_id', 'planned_start', 'planned_end'], unique=False, schema='production')

    op.create_table('plan_allocations',
    sa.Column('plan_item_id', sa.Uuid(), nullable=False, comment='计划项'),
    sa.Column('batch_id', sa.Uuid(), nullable=False, comment='批次'),
    sa.Column('allocated_quantity', sa.Float(), nullable=False, comment='本批次承担数量'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_plan_allocations', 'plan_allocations', ['plan_item_id', 'batch_id'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('demand_allocations',
    sa.Column('demand_id', sa.Uuid(), nullable=False, comment='需求'),
    sa.Column('plan_item_id', sa.Uuid(), nullable=False, comment='计划项'),
    sa.Column('allocated_quantity', sa.Float(), nullable=False, comment='该计划项为此需求承担的数量'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('uq_production_demand_allocations', 'demand_allocations', ['demand_id', 'plan_item_id'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))

    # --- extend batches table ---
    # Drop old status CHECK constraint and recreate with 7 states
    op.execute("ALTER TABLE production.batches DROP CONSTRAINT IF EXISTS ck_production_batches_status")
    op.execute("""
        ALTER TABLE production.batches ADD CONSTRAINT ck_production_batches_status
        CHECK (status IN ('draft', 'scheduled', 'released', 'pending', 'in_progress', 'completed', 'cancelled'))
    """)

    op.add_column('batches',
        sa.Column('creation_type', sa.String(length=20), server_default='direct', nullable=False, comment='plan/rework/outsource/trial/direct'),
        schema='production')
    op.add_column('batches',
        sa.Column('plan_version', sa.Integer(), nullable=True, comment='由计划生成时记录所依据的计划版本'),
        schema='production')

    op.execute("""
        ALTER TABLE production.batches ADD CONSTRAINT ck_production_batches_creation_type
        CHECK (creation_type IN ('plan', 'rework', 'outsource', 'trial', 'direct'))
    """)


def downgrade() -> None:
    # --- revert batches changes ---
    op.execute("ALTER TABLE production.batches DROP CONSTRAINT IF EXISTS ck_production_batches_creation_type")
    op.execute("ALTER TABLE production.batches DROP CONSTRAINT IF EXISTS ck_production_batches_status")

    op.drop_column('batches', 'plan_version', schema='production')
    op.drop_column('batches', 'creation_type', schema='production')

    op.execute("""
        ALTER TABLE production.batches ADD CONSTRAINT ck_production_batches_status
        CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled'))
    """)

    # --- drop planning tables ---
    op.drop_index('uq_production_demand_allocations', table_name='demand_allocations', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('demand_allocations', schema='production')
    op.drop_index('uq_production_plan_allocations', table_name='plan_allocations', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('plan_allocations', schema='production')
    op.drop_index('ix_production_plan_items_equipment_time', table_name='plan_items', schema='production')
    op.drop_index('uq_production_plan_items_no', table_name='plan_items', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('plan_items', schema='production')
    op.drop_index('uq_production_plan_orders_no', table_name='plan_orders', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('plan_orders', schema='production')
    op.drop_index('uq_production_demands_no', table_name='demands', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('demands', schema='production')
