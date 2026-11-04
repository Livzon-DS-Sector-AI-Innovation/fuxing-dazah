"""quality add stocktake

Revision ID: 82d08bacd627
Revises: 295241149973
Create Date: 2026-10-12 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '82d08bacd627'
down_revision: Union[str, None] = '295241149973'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_stocktake_items',
    sa.Column('sheet_id', sa.Uuid(), nullable=False, comment='逻辑引用 quality_stocktake_sheets.id（无 FK）'),
    sa.Column('container_no', sa.String(length=100), nullable=False, comment='扫到的容器号'),
    sa.Column('result', sa.String(length=32), nullable=False, comment='matched 在库匹配 / out_of_scope 系统有但不在库 / not_found 系统不存在'),
    sa.Column('status_snapshot', sa.String(length=32), nullable=True, comment='扫描时容器状态快照'),
    sa.Column('material_code', sa.String(length=100), nullable=True, comment='物料代码快照（系统有容器时）'),
    sa.Column('material_name', sa.String(length=200), nullable=True, comment='物料名称快照'),
    sa.Column('scanned_by', sa.Uuid(), nullable=True, comment='扫码人'),
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
    op.create_index('ix_quality_stocktake_item_sheet', 'quality_stocktake_items', ['sheet_id'], unique=False, schema='quality')
    op.create_index('uq_quality_stocktake_item_container', 'quality_stocktake_items', ['sheet_id', 'container_no'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('quality_stocktake_sheets',
    sa.Column('sheet_no', sa.String(length=100), nullable=False, comment='盘点单号 ST+YYMMDD+序号'),
    sa.Column('scope_material_code', sa.String(length=100), nullable=True, comment='盘点范围物料代码，空=全部物料'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='in_progress/completed/void'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('expected_count', sa.Integer(), nullable=False, comment='系统在库容器数'),
    sa.Column('scanned_count', sa.Integer(), nullable=False, comment='实扫容器数'),
    sa.Column('missing_count', sa.Integer(), nullable=False, comment='盘亏（系统在库未扫到）'),
    sa.Column('extra_count', sa.Integer(), nullable=False, comment='盘盈（扫到但系统不在库/不存在）'),
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
    op.create_index('ix_quality_stocktake_sheet_status', 'quality_stocktake_sheets', ['status'], unique=False, schema='quality')
    op.create_index('uq_quality_stocktake_sheet_no', 'quality_stocktake_sheets', ['sheet_no'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_quality_stocktake_item_container', table_name='quality_stocktake_items', schema='quality')
    op.drop_index('ix_quality_stocktake_item_sheet', table_name='quality_stocktake_items', schema='quality')
    op.drop_table('quality_stocktake_items', schema='quality')
    op.drop_index('uq_quality_stocktake_sheet_no', table_name='quality_stocktake_sheets', schema='quality')
    op.drop_index('ix_quality_stocktake_sheet_status', table_name='quality_stocktake_sheets', schema='quality')
    op.drop_table('quality_stocktake_sheets', schema='quality')
