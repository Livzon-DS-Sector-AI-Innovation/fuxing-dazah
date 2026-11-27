"""quality add material containers and movements

Revision ID: bc6c688c72e8
Revises: fc1194b67aa7
Create Date: 2026-10-10 10:34:34.255001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bc6c688c72e8'
down_revision: Union[str, None] = 'fc1194b67aa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_container_movements',
    sa.Column('container_id', sa.Uuid(), nullable=False, comment='逻辑引用 quality.quality_material_containers.id（无 FK）'),
    sa.Column('container_no', sa.String(length=100), nullable=False, comment='操作时容器号快照'),
    sa.Column('op_type', sa.String(length=16), nullable=False, comment='in 入库登记 / out 领料出库 / status 人工流转'),
    sa.Column('from_status', sa.String(length=32), nullable=False, comment='操作前状态'),
    sa.Column('to_status', sa.String(length=32), nullable=False, comment='操作后状态'),
    sa.Column('operator', sa.Uuid(), nullable=True, comment='操作人'),
    sa.Column('op_at', sa.DateTime(timezone=True), nullable=False, comment='操作时间'),
    sa.Column('related_doc', sa.String(length=100), nullable=True, comment='关联单据号（领料单等）'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
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
    op.create_index('ix_quality_container_mv_container', 'quality_container_movements', ['container_id'], unique=False, schema='quality')
    op.create_table('quality_material_containers',
    sa.Column('container_no', sa.String(length=100), nullable=False, comment='容器号，如 MC-VAN-20261010-0001'),
    sa.Column('material_code', sa.String(length=100), nullable=False, comment='物料代码'),
    sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称'),
    sa.Column('vendor_code', sa.String(length=100), nullable=True, comment='供应商代码'),
    sa.Column('inbound_batch_no', sa.String(length=100), nullable=False, comment='进厂批号'),
    sa.Column('expiry_date', sa.String(length=32), nullable=True, comment='复验期 YYYY-MM-DD（过期拦截用，阶段3）'),
    sa.Column('seq', sa.Integer(), nullable=False, comment='该批第几瓶（容器号末段流水）'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='labeled/in_warehouse/qualified/issued/returned/void'),
    sa.Column('qr_issued_by', sa.Uuid(), nullable=True, comment='赋码人'),
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
    op.create_index('ix_quality_container_batch', 'quality_material_containers', ['inbound_batch_no'], unique=False, schema='quality')
    op.create_index('ix_quality_container_status', 'quality_material_containers', ['status'], unique=False, schema='quality')
    op.create_index('uq_quality_container_no', 'quality_material_containers', ['container_no'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_quality_container_no', table_name='quality_material_containers', schema='quality')
    op.drop_index('ix_quality_container_status', table_name='quality_material_containers', schema='quality')
    op.drop_index('ix_quality_container_batch', table_name='quality_material_containers', schema='quality')
    op.drop_table('quality_material_containers', schema='quality')
    op.drop_index('ix_quality_container_mv_container', table_name='quality_container_movements', schema='quality')
    op.drop_table('quality_container_movements', schema='quality')
