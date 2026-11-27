"""quality add material requests standards and task kind

Revision ID: 1b88f752e31b
Revises: 46c87af24fab
Create Date: 2026-10-14 09:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1b88f752e31b'
down_revision: Union[str, None] = '46c87af24fab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_material_requests',
    sa.Column('request_no', sa.String(length=100), nullable=False, comment='请验单号 MR+YYMMDD+序号'),
    sa.Column('material_code', sa.String(length=100), nullable=False, comment='物料代码（逻辑引用 quality_materials.code）'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称快照'),
    sa.Column('vendor_code', sa.String(length=100), nullable=True, comment='供应商代码'),
    sa.Column('vendor_name', sa.String(length=100), nullable=True, comment='供应商名称快照'),
    sa.Column('inbound_batch_no', sa.String(length=100), nullable=False, comment='进厂批号'),
    sa.Column('material_request_id', sa.Uuid(), nullable=True, comment='所属请验单（逻辑引用 quality.quality_material_requests.id，放行联动用）'),
    sa.Column('inbound_qty', sa.Integer(), nullable=False, comment='到货数量（瓶/桶）'),
    sa.Column('inbound_date', sa.String(length=32), nullable=True, comment='到货日期 YYYY-MM-DD'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='pending_sample/sampled/in_test/released/rejected/conceded/void'),
    sa.Column('sampled_at', sa.String(length=32), nullable=True, comment='取样日期'),
    sa.Column('sampled_qty', sa.Integer(), nullable=True, comment='取样数量'),
    sa.Column('sampled_by', sa.Uuid(), nullable=True, comment='取样人'),
    sa.Column('verdict', sa.String(length=32), nullable=True, comment='放行结论 release/reject/concede'),
    sa.Column('verdict_remark', sa.String(length=200), nullable=True, comment='放行备注（拒收/让步原因）'),
    sa.Column('released_by', sa.Uuid(), nullable=True, comment='放行人'),
    sa.Column('released_at', sa.String(length=32), nullable=True, comment='放行日期 YYYY-MM-DD'),
    sa.Column('task_id', sa.Uuid(), nullable=True, comment='关联物料检验任务（逻辑引用 quality_test_tasks.id）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('ix_quality_material_request_batch', 'quality_material_requests', ['inbound_batch_no'], unique=False, schema='quality')
    op.create_index('ix_quality_material_request_status', 'quality_material_requests', ['status'], unique=False, schema='quality')
    op.create_index('uq_quality_material_request_no', 'quality_material_requests', ['request_no'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('quality_material_standard_items',
    sa.Column('standard_id', sa.Uuid(), nullable=False, comment='逻辑引用 quality_material_standards.id（无 FK）'),
    sa.Column('seq', sa.Integer(), nullable=True, comment='序号'),
    sa.Column('category', sa.String(length=100), nullable=True, comment='项目大类'),
    sa.Column('item_name', sa.String(length=200), nullable=False, comment='项目名称'),
    sa.Column('sop_no', sa.String(length=100), nullable=True, comment='方法 SOP 号'),
    sa.Column('standard_text', sa.String(length=300), nullable=True, comment='合格标准原文'),
    sa.Column('operator', sa.String(length=10), nullable=True, comment='≤ ≥ < > 范围'),
    sa.Column('limit_min', sa.Float(), nullable=True, comment='限度下限'),
    sa.Column('limit_max', sa.Float(), nullable=True, comment='限度上限'),
    sa.Column('method_source', sa.String(length=64), nullable=True, comment='方法来源'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('uq_quality_material_std_item', 'quality_material_standard_items', ['standard_id', 'sop_no', 'item_name'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('quality_material_standards',
    sa.Column('material_code', sa.String(length=100), nullable=False, comment='物料代码'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称快照'),
    sa.Column('vendor_code', sa.String(length=100), nullable=True, comment='供应商代码（空=通用标准）'),
    sa.Column('version', sa.String(length=32), nullable=True, comment='版本号'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('uq_quality_material_std', 'quality_material_standards', ['material_code', 'vendor_code'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.add_column('quality_material_containers', sa.Column('material_request_id', sa.Uuid(), nullable=True, comment='所属请验单（逻辑引用 quality.quality_material_requests.id，放行联动用）'), schema='quality')
    op.add_column('quality_test_tasks', sa.Column('task_kind', sa.String(length=32), nullable=False, server_default='product', comment='product 产品检验 / material 物料检验'), schema='quality')
    op.add_column('quality_test_tasks', sa.Column('material_request_id', sa.Uuid(), nullable=True, comment='物料检验任务关联的请验单（逻辑引用 quality.quality_material_requests.id）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_material_containers', 'material_request_id', schema='quality')
    op.drop_column('quality_test_tasks', 'material_request_id', schema='quality')
    op.drop_column('quality_test_tasks', 'task_kind', schema='quality')
    op.drop_index('uq_quality_material_std_item', table_name='quality_material_standard_items', schema='quality')
    op.drop_table('quality_material_standard_items', schema='quality')
    op.drop_index('uq_quality_material_std', table_name='quality_material_standards', schema='quality')
    op.drop_table('quality_material_standards', schema='quality')
    op.drop_index('uq_quality_material_request_no', table_name='quality_material_requests', schema='quality')
    op.drop_index('ix_quality_material_request_status', table_name='quality_material_requests', schema='quality')
    op.drop_index('ix_quality_material_request_batch', table_name='quality_material_requests', schema='quality')
    op.drop_table('quality_material_requests', schema='quality')
