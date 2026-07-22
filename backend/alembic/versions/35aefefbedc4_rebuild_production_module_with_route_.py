"""rebuild production module with route graph model

DROP 旧 production 9 表（数据已确认不保留），CREATE 路线图模型新 10 表。
autogenerate 混入的其他模块变更已全部手工清除，本迁移只含 production schema DDL。

Revision ID: 35aefefbedc4
Revises: 20fda41cfdd3
Create Date: 2026-07-15 12:24:29.929763
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '35aefefbedc4'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")

    # ---- DROP 旧 9 表（引用方在前：batches 引用 process_specs，须先删） ----
    op.drop_table('material_balances', schema='production')
    op.drop_table('production_records', schema='production')
    op.drop_table('process_parameters', schema='production')
    op.drop_table('process_steps', schema='production')
    op.drop_table('batch_materials', schema='production')
    op.drop_table('plan_tasks', schema='production')
    op.drop_table('batches', schema='production')
    op.drop_table('production_plans', schema='production')
    op.drop_table('process_specs', schema='production')

    # ---- CREATE 新 10 表 ----
    op.create_table('products',
    sa.Column('product_code', sa.String(length=50), nullable=False, comment='产品编码'),
    sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
    sa.Column('unit', sa.String(length=20), nullable=False, comment='默认计量单位'),
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
    schema='production'
    )
    op.create_index('uq_production_products_code', 'products', ['product_code'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('process_routes',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='产品ID，逻辑引用 production.products.id'),
    sa.Column('version', sa.Integer(), nullable=False, comment='版本号，同产品内递增'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='路线名称'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='draft/published/archived'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name='ck_production_routes_status'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_routes_product', 'process_routes', ['product_id'], unique=False, schema='production')
    op.create_index('uq_production_routes_product_version', 'process_routes', ['product_id', 'version'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('route_nodes',
    sa.Column('route_id', sa.Uuid(), nullable=False, comment='所属路线'),
    sa.Column('node_code', sa.String(length=50), nullable=False, comment='节点编码，路线内唯一'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='工序名称'),
    sa.Column('stage_name', sa.String(length=100), nullable=True, comment='工段分组标签（发酵/提炼/精制），纯展示'),
    sa.Column('node_type', sa.String(length=20), nullable=False, comment='节点类型，现阶段恒为 process，预留扩展'),
    sa.Column('sort_order', sa.Integer(), nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_route_nodes_route', 'route_nodes', ['route_id'], unique=False, schema='production')
    op.create_index('uq_production_route_nodes_code', 'route_nodes', ['route_id', 'node_code'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('route_edges',
    sa.Column('route_id', sa.Uuid(), nullable=False, comment='所属路线'),
    sa.Column('from_node_id', sa.Uuid(), nullable=False, comment='起始节点'),
    sa.Column('to_node_id', sa.Uuid(), nullable=False, comment='目标节点'),
    sa.Column('edge_type', sa.String(length=20), nullable=False, comment='normal/rework'),
    sa.Column('is_batch_boundary', sa.Boolean(), nullable=False, comment='是否批次边界'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注，如：不合格时'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("NOT (edge_type = 'rework' AND is_batch_boundary)", name='ck_production_route_edges_rework_boundary'),
    sa.CheckConstraint("edge_type IN ('normal', 'rework')", name='ck_production_route_edges_type'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_route_edges_route', 'route_edges', ['route_id'], unique=False, schema='production')
    op.create_index('uq_production_route_edges', 'route_edges', ['route_id', 'from_node_id', 'to_node_id', 'edge_type'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('node_field_defs',
    sa.Column('node_id', sa.Uuid(), nullable=False, comment='所属节点'),
    sa.Column('field_key', sa.String(length=50), nullable=False, comment='字段键，节点内唯一'),
    sa.Column('field_label', sa.String(length=100), nullable=False, comment='显示名'),
    sa.Column('field_group', sa.String(length=50), nullable=True, comment='分组标签：过程检测/产出物/物料消耗（未来）'),
    sa.Column('phase', sa.String(length=10), nullable=False, comment='start=开始工序时填 / end=结束工序时填'),
    sa.Column('data_type', sa.String(length=20), nullable=False, comment='numeric/text/boolean/select'),
    sa.Column('options', sa.JSON(), nullable=True, comment='select 选项列表'),
    sa.Column('unit', sa.String(length=20), nullable=True, comment='单位'),
    sa.Column('required', sa.Boolean(), nullable=False, comment='必填'),
    sa.Column('min_value', sa.Float(), nullable=True, comment='numeric 下限，超出判 is_abnormal'),
    sa.Column('max_value', sa.Float(), nullable=True, comment='numeric 上限，超出判 is_abnormal'),
    sa.Column('sort_order', sa.Integer(), nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("data_type IN ('numeric', 'text', 'boolean', 'select')", name='ck_production_field_defs_data_type'),
    sa.CheckConstraint("phase IN ('start', 'end')", name='ck_production_field_defs_phase'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_node_field_defs_node', 'node_field_defs', ['node_id'], unique=False, schema='production')
    op.create_index('uq_production_node_field_defs', 'node_field_defs', ['node_id', 'field_key'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('batches',
    sa.Column('batch_no', sa.String(length=50), nullable=False, comment='批号'),
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='产品'),
    sa.Column('route_id', sa.Uuid(), nullable=False, comment='创建时锁定的路线版本'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='pending/in_progress/completed/cancelled'),
    sa.Column('quantity', sa.Float(), nullable=True, comment='本批数量'),
    sa.Column('unit', sa.String(length=20), nullable=True, comment='单位'),
    sa.Column('entry_node_id', sa.Uuid(), nullable=True, comment='入口节点：derive/merge 产生的批次记录边界边的 to_node；根批次为空'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'cancelled')", name='ck_production_batches_status'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_batches_product_status', 'batches', ['product_id', 'status'], unique=False, schema='production')
    op.create_index('uq_production_batches_no', 'batches', ['batch_no'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('batch_links',
    sa.Column('parent_batch_id', sa.Uuid(), nullable=False, comment='父批次'),
    sa.Column('child_batch_id', sa.Uuid(), nullable=False, comment='子批次'),
    sa.Column('edge_id', sa.Uuid(), nullable=True, comment='走的哪条边界边；临时偏离时为空'),
    sa.Column('allocated_qty', sa.Float(), nullable=True, comment='父批分给此子批的量'),
    sa.Column('is_deviation', sa.Boolean(), nullable=False, comment='未走预定义边界'),
    sa.Column('deviation_reason', sa.Text(), nullable=True, comment='偏离原因，偏离时必填'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_batch_links_child', 'batch_links', ['child_batch_id'], unique=False, schema='production')
    op.create_index('ix_production_batch_links_parent', 'batch_links', ['parent_batch_id'], unique=False, schema='production')
    op.create_index('uq_production_batch_links', 'batch_links', ['parent_batch_id', 'child_batch_id'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('node_executions',
    sa.Column('batch_id', sa.Uuid(), nullable=False, comment='批次'),
    sa.Column('node_id', sa.Uuid(), nullable=False, comment='工序节点'),
    sa.Column('execution_seq', sa.Integer(), nullable=False, comment='同批次同节点第几次执行'),
    sa.Column('status', sa.String(length=20), nullable=False, comment='in_progress/completed/aborted'),
    sa.Column('owner_id', sa.Uuid(), nullable=True, comment='工序负责人，逻辑引用 identity.users.id'),
    sa.Column('owner_name', sa.String(length=50), nullable=True, comment='负责人姓名快照'),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, comment='开始时间'),
    sa.Column('started_by', sa.Uuid(), nullable=True, comment='开始提交人'),
    sa.Column('started_by_name', sa.String(length=50), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True, comment='结束时间'),
    sa.Column('finished_by', sa.Uuid(), nullable=True, comment='结束提交人'),
    sa.Column('finished_by_name', sa.String(length=50), nullable=True),
    sa.Column('is_deviation', sa.Boolean(), nullable=False, comment='流转未在路线中定义'),
    sa.Column('deviation_reason', sa.Text(), nullable=True),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('in_progress', 'completed', 'aborted')", name='ck_production_node_executions_status'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_node_executions_batch', 'node_executions', ['batch_id'], unique=False, schema='production')
    op.create_index('ix_production_node_executions_node', 'node_executions', ['node_id'], unique=False, schema='production')
    op.create_index('uq_production_node_executions_seq', 'node_executions', ['batch_id', 'node_id', 'execution_seq'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('node_execution_equipments',
    sa.Column('execution_id', sa.Uuid(), nullable=False, comment='所属执行'),
    sa.Column('equipment_id', sa.Uuid(), nullable=False, comment='设备，逻辑引用 equipment.equipments.id'),
    sa.Column('equipment_no', sa.String(length=50), nullable=False, comment='设备编号快照'),
    sa.Column('equipment_name', sa.String(length=200), nullable=False, comment='设备名称快照'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_exec_equipments_exec', 'node_execution_equipments', ['execution_id'], unique=False, schema='production')
    op.create_table('node_field_values',
    sa.Column('execution_id', sa.Uuid(), nullable=False, comment='所属执行'),
    sa.Column('field_def_id', sa.Uuid(), nullable=False, comment='对应字段定义'),
    sa.Column('field_key', sa.String(length=50), nullable=False, comment='快照'),
    sa.Column('field_label', sa.String(length=100), nullable=False, comment='快照'),
    sa.Column('unit', sa.String(length=20), nullable=True, comment='快照'),
    sa.Column('phase', sa.String(length=10), nullable=False, comment='快照 start/end'),
    sa.Column('value_text', sa.Text(), nullable=True),
    sa.Column('value_numeric', sa.Float(), nullable=True),
    sa.Column('value_bool', sa.Boolean(), nullable=True),
    sa.Column('is_abnormal', sa.Boolean(), nullable=False, comment='numeric 超出 min/max 自动判定'),
    sa.Column('remark', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='production'
    )
    op.create_index('ix_production_node_field_values_exec', 'node_field_values', ['execution_id'], unique=False, schema='production')
    op.create_index('uq_production_node_field_values', 'node_field_values', ['execution_id', 'field_def_id'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    # ---- DROP 新 10 表（表上索引随表删除） ----
    op.drop_table('node_field_values', schema='production')
    op.drop_table('node_execution_equipments', schema='production')
    op.drop_table('node_executions', schema='production')
    op.drop_table('batch_links', schema='production')
    op.drop_table('batches', schema='production')
    op.drop_table('node_field_defs', schema='production')
    op.drop_table('route_edges', schema='production')
    op.drop_table('route_nodes', schema='production')
    op.drop_table('process_routes', schema='production')
    op.drop_table('products', schema='production')

    # ---- 重建旧 9 表（被引用方在前；旧数据不恢复，仅还原表结构） ----
    op.create_table('process_specs',
    sa.Column('spec_code', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='规程编号'),
    sa.Column('spec_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='规程名称'),
    sa.Column('product_code', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='产品编码'),
    sa.Column('product_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='产品名称'),
    sa.Column('version', sa.VARCHAR(length=20), server_default=sa.text("'1.0'::character varying"), autoincrement=False, nullable=False, comment='版本号'),
    sa.Column('status', sa.VARCHAR(length=32), server_default=sa.text("'draft'::character varying"), autoincrement=False, nullable=False, comment='状态'),
    sa.Column('effective_date', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='生效日期'),
    sa.Column('approved_by', sa.UUID(), autoincrement=False, nullable=True, comment='批准人'),
    sa.Column('approved_by_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='批准人姓名'),
    sa.Column('approved_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='批准时间'),
    sa.Column('supersedes_version', sa.VARCHAR(length=20), autoincrement=False, nullable=True, comment='替代版本'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['identity.users.id'], name=op.f('process_specs_approved_by_fkey')),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('process_specs_created_by_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('process_specs_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('process_specs_pkey')),
    sa.UniqueConstraint('spec_code', 'version', name=op.f('uq_process_specs_code_version'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='production'
    )
    op.create_table('production_plans',
    sa.Column('plan_no', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='计划编号'),
    sa.Column('plan_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='计划名称'),
    sa.Column('plan_type', sa.VARCHAR(length=50), autoincrement=False, nullable=True, comment='计划类型:月计划/周计划'),
    sa.Column('plan_month', sa.VARCHAR(length=7), autoincrement=False, nullable=True, comment='计划月份YYYY-MM'),
    sa.Column('status', sa.VARCHAR(length=32), server_default=sa.text("'draft'::character varying"), autoincrement=False, nullable=False, comment='状态'),
    sa.Column('total_batches', sa.INTEGER(), autoincrement=False, nullable=True, comment='总批次'),
    sa.Column('completed_batches', sa.INTEGER(), autoincrement=False, nullable=True, comment='已完成批次'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('production_plans_created_by_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('production_plans_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('production_plans_pkey')),
    sa.UniqueConstraint('plan_no', name=op.f('uq_production_plans_plan_no'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='production'
    )
    op.create_table('batches',
    sa.Column('batch_no', sa.String(length=64), nullable=False, comment='批次号'),
    sa.Column('product_code', sa.String(length=64), nullable=False, comment='产品编码'),
    sa.Column('product_name', sa.String(length=255), nullable=True, comment='产品名称'),
    sa.Column('specification', sa.String(length=100), nullable=True, comment='规格'),
    sa.Column('unit', sa.String(length=20), nullable=True, comment='单位'),
    sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态'),
    sa.Column('planned_qty', sa.Float(), nullable=True, comment='计划数量'),
    sa.Column('actual_qty', sa.Float(), nullable=True, comment='实际产出数量'),
    sa.Column('input_qty', sa.Float(), nullable=True, comment='实际投入数量'),
    sa.Column('process_spec_id', sa.UUID(), nullable=True, comment='工艺规程ID'),
    sa.Column('production_line', sa.String(length=100), nullable=True, comment='生产线'),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=True, comment='开始时间'),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True, comment='结束时间'),
    sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['process_spec_id'], ['production.process_specs.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_no', name='uq_batches_batch_no'),
    schema='production'
    )
    op.create_table('plan_tasks',
    sa.Column('plan_id', sa.UUID(), autoincrement=False, nullable=False, comment='计划ID'),
    sa.Column('product_code', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='产品编码'),
    sa.Column('product_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='产品名称'),
    sa.Column('batch_qty', sa.INTEGER(), autoincrement=False, nullable=True, comment='批次数量'),
    sa.Column('assigned_to', sa.UUID(), autoincrement=False, nullable=True, comment='负责人'),
    sa.Column('assigned_to_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='负责人姓名'),
    sa.Column('due_date', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='计划完成日期'),
    sa.Column('status', sa.VARCHAR(length=32), server_default=sa.text("'pending'::character varying"), autoincrement=False, nullable=False, comment='状态'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['identity.users.id'], name=op.f('plan_tasks_assigned_to_fkey')),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('plan_tasks_created_by_fkey')),
    sa.ForeignKeyConstraint(['plan_id'], ['production.production_plans.id'], name=op.f('plan_tasks_plan_id_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('plan_tasks_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('plan_tasks_pkey')),
    schema='production'
    )
    op.create_table('process_steps',
    sa.Column('spec_id', sa.UUID(), autoincrement=False, nullable=False, comment='规程ID'),
    sa.Column('step_no', sa.INTEGER(), autoincrement=False, nullable=False, comment='步骤序号'),
    sa.Column('step_name', sa.VARCHAR(length=255), autoincrement=False, nullable=False, comment='步骤名称'),
    sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True, comment='步骤描述'),
    sa.Column('equipment_type', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='设备类型'),
    sa.Column('equipment_spec', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='设备规格'),
    sa.Column('duration_minutes', sa.INTEGER(), autoincrement=False, nullable=True, comment='持续时间(分钟)'),
    sa.Column('sequence_order', sa.INTEGER(), autoincrement=False, nullable=True, comment='排序顺序'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('process_steps_created_by_fkey')),
    sa.ForeignKeyConstraint(['spec_id'], ['production.process_specs.id'], name=op.f('process_steps_spec_id_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('process_steps_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('process_steps_pkey')),
    schema='production'
    )
    op.create_table('batch_materials',
    sa.Column('batch_id', sa.UUID(), autoincrement=False, nullable=False, comment='批次ID'),
    sa.Column('material_code', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='物料编码'),
    sa.Column('material_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='物料名称'),
    sa.Column('material_type', sa.VARCHAR(length=50), autoincrement=False, nullable=True, comment='物料类型'),
    sa.Column('unit', sa.VARCHAR(length=20), autoincrement=False, nullable=True, comment='单位'),
    sa.Column('planned_qty', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='计划用量'),
    sa.Column('actual_qty', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='实际用量'),
    sa.Column('lot_no', sa.VARCHAR(length=64), autoincrement=False, nullable=True, comment='批号/批次'),
    sa.Column('stage', sa.VARCHAR(length=50), autoincrement=False, nullable=True, comment='工序阶段'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['production.batches.id'], name=op.f('batch_materials_batch_id_fkey')),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('batch_materials_created_by_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('batch_materials_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('batch_materials_pkey')),
    schema='production'
    )
    op.create_table('production_records',
    sa.Column('batch_id', sa.UUID(), autoincrement=False, nullable=False, comment='批次ID'),
    sa.Column('record_no', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='记录编号'),
    sa.Column('step_no', sa.INTEGER(), autoincrement=False, nullable=True, comment='步骤序号'),
    sa.Column('step_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='步骤名称'),
    sa.Column('operator', sa.UUID(), autoincrement=False, nullable=True, comment='操作人'),
    sa.Column('operator_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='操作人姓名'),
    sa.Column('operation_time', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False, comment='操作时间'),
    sa.Column('operation_type', sa.VARCHAR(length=32), autoincrement=False, nullable=False, comment='操作类型'),
    sa.Column('parameters', sa.TEXT(), autoincrement=False, nullable=True, comment='参数JSON'),
    sa.Column('result', sa.TEXT(), autoincrement=False, nullable=True, comment='操作结果'),
    sa.Column('remarks', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['production.batches.id'], name=op.f('production_records_batch_id_fkey')),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('production_records_created_by_fkey')),
    sa.ForeignKeyConstraint(['operator'], ['identity.users.id'], name=op.f('production_records_operator_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('production_records_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('production_records_pkey')),
    sa.UniqueConstraint('batch_id', 'record_no', name=op.f('uq_production_records_batch_record'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='production'
    )
    op.create_table('material_balances',
    sa.Column('batch_id', sa.UUID(), autoincrement=False, nullable=False, comment='批次ID'),
    sa.Column('input_qty', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='投入总量'),
    sa.Column('output_qty', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='产出总量'),
    sa.Column('loss_qty', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='损耗总量'),
    sa.Column('balance_rate', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='平衡率(%)'),
    sa.Column('min_balance_rate', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False, comment='最低平衡率(%)'),
    sa.Column('is_balanced', sa.BOOLEAN(), autoincrement=False, nullable=False, comment='是否平衡'),
    sa.Column('deviation_rate', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='偏差率(%)'),
    sa.Column('calculated_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='计算时间'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['production.batches.id'], name=op.f('material_balances_batch_id_fkey')),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('material_balances_created_by_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('material_balances_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('material_balances_pkey')),
    sa.UniqueConstraint('batch_id', name=op.f('uq_material_balances_batch_id'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='production'
    )
    op.create_table('process_parameters',
    sa.Column('step_id', sa.UUID(), autoincrement=False, nullable=False, comment='步骤ID'),
    sa.Column('param_name', sa.VARCHAR(length=255), autoincrement=False, nullable=False, comment='参数名称'),
    sa.Column('param_code', sa.VARCHAR(length=64), autoincrement=False, nullable=True, comment='参数编码'),
    sa.Column('unit', sa.VARCHAR(length=20), autoincrement=False, nullable=True, comment='单位'),
    sa.Column('min_value', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='最小值'),
    sa.Column('max_value', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='最大值'),
    sa.Column('target_value', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='目标值'),
    sa.Column('is_critical', sa.BOOLEAN(), autoincrement=False, nullable=False, comment='是否关键参数'),
    sa.Column('data_type', sa.VARCHAR(length=20), autoincrement=False, nullable=True, comment='数据类型:numeric/text/boolean'),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('process_parameters_created_by_fkey')),
    sa.ForeignKeyConstraint(['step_id'], ['production.process_steps.id'], name=op.f('process_parameters_step_id_fkey')),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('process_parameters_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('process_parameters_pkey')),
    schema='production'
    )
