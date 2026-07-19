"""add intermediate product ledger

Revision ID: cf35485d0c6b
Revises: 79ae97a9950f
Create Date: 2026-07-17 14:05:39.743513
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf35485d0c6b'
down_revision: Union[str, None] = '79ae97a9950f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建中间体台账相关表。"""
    op.create_table('intermediate_types',
        sa.Column('code', sa.String(length=50), nullable=False, comment='中间体编码'),
        sa.Column('name', sa.String(length=200), nullable=False, comment='中间体名称'),
        sa.Column('category', sa.String(length=100), nullable=True, comment='分类：发酵液/结晶粉/湿品等'),
        sa.Column('default_unit', sa.String(length=20), nullable=True, comment='默认单位'),
        sa.Column('description', sa.Text(), nullable=True, comment='说明'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='production'
    )
    op.create_index('uq_production_intermediate_types_code', 'intermediate_types', ['code'],
                    unique=True, schema='production',
                    postgresql_where=sa.text('is_deleted = false'))

    op.create_table('route_node_intermediates',
        sa.Column('node_id', sa.Uuid(), nullable=False, comment='所属节点'),
        sa.Column('intermediate_type_id', sa.Uuid(), nullable=False, comment='中间体类型'),
        sa.Column('direction', sa.String(length=10), nullable=False, comment='产出(output) / 消耗(input)'),
        sa.Column('unit_override', sa.String(length=20), nullable=True, comment='覆盖默认单位'),
        sa.Column('required', sa.Boolean(), nullable=False, comment='是否必填'),
        sa.Column('sort_order', sa.Integer(), nullable=False, comment='排序'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.CheckConstraint("direction IN ('output', 'input')",
                          name='ck_production_node_intermediates_direction'),
        sa.PrimaryKeyConstraint('id'),
        schema='production'
    )
    op.create_index('ix_production_node_intermediates_node', 'route_node_intermediates', ['node_id'],
                    unique=False, schema='production')
    op.create_index('uq_production_node_intermediates', 'route_node_intermediates',
                    ['node_id', 'intermediate_type_id', 'direction'],
                    unique=True, schema='production',
                    postgresql_where=sa.text('is_deleted = false'))

    op.create_table('batch_intermediate_outputs',
        sa.Column('batch_id', sa.Uuid(), nullable=False, comment='所属批次'),
        sa.Column('execution_id', sa.Uuid(), nullable=False, comment='产出所属执行'),
        sa.Column('node_id', sa.Uuid(), nullable=False, comment='产出节点'),
        sa.Column('intermediate_type_id', sa.Uuid(), nullable=False, comment='中间体类型'),
        sa.Column('intermediate_batch_no', sa.String(length=100), nullable=True, comment='中间体批号，为空则默认用批次号'),
        sa.Column('quantity', sa.Float(), nullable=False, comment='数量'),
        sa.Column('unit', sa.String(length=20), nullable=False, comment='单位'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='production'
    )
    op.create_index('ix_production_outputs_batch', 'batch_intermediate_outputs', ['batch_id'],
                    unique=False, schema='production')
    op.create_index('ix_production_outputs_execution', 'batch_intermediate_outputs', ['execution_id'],
                    unique=False, schema='production')

    op.create_table('batch_intermediate_consumptions',
        sa.Column('batch_id', sa.Uuid(), nullable=False, comment='所属批次'),
        sa.Column('execution_id', sa.Uuid(), nullable=False, comment='消耗所属执行'),
        sa.Column('node_id', sa.Uuid(), nullable=False, comment='消耗节点'),
        sa.Column('intermediate_type_id', sa.Uuid(), nullable=False, comment='中间体类型'),
        sa.Column('output_id', sa.Uuid(), nullable=False, comment='引用的产出记录，溯源关键字段'),
        sa.Column('quantity', sa.Float(), nullable=False, comment='消耗数量'),
        sa.Column('unit', sa.String(length=20), nullable=False, comment='单位'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='production'
    )
    op.create_index('ix_production_consumptions_batch', 'batch_intermediate_consumptions', ['batch_id'],
                    unique=False, schema='production')
    op.create_index('ix_production_consumptions_execution', 'batch_intermediate_consumptions', ['execution_id'],
                    unique=False, schema='production')
    op.create_index('ix_production_consumptions_output', 'batch_intermediate_consumptions', ['output_id'],
                    unique=False, schema='production')


def downgrade() -> None:
    """删除中间体台账相关表。"""
    op.drop_table('batch_intermediate_consumptions', schema='production')
    op.drop_table('batch_intermediate_outputs', schema='production')
    op.drop_table('route_node_intermediates', schema='production')
    op.drop_table('intermediate_types', schema='production')
