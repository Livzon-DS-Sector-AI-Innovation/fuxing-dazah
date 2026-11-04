"""quality add material dictionary

Revision ID: 01fb7635be41
Revises: bc6c688c72e8
Create Date: 2026-10-10 14:58:55.550049
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '01fb7635be41'
down_revision: Union[str, None] = 'bc6c688c72e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_materials',
    sa.Column('code', sa.String(length=100), nullable=False, comment='物料代码（容器号中段）'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='物料名称'),
    sa.Column('category', sa.String(length=32), nullable=True, comment='类别：原料/辅料/包材/溶剂'),
    sa.Column('vendor_name', sa.String(length=100), nullable=True, comment='默认供应商名称'),
    sa.Column('pack_spec', sa.String(length=50), nullable=True, comment='包装规格，如 5kg/听'),
    sa.Column('min_stock', sa.Integer(), nullable=True, comment='安全库存阈值（瓶/桶数），采购建议依据'),
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
    op.create_index('ix_quality_material_name', 'quality_materials', ['name'], unique=False, schema='quality')
    op.create_index('uq_quality_material_code', 'quality_materials', ['code'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_quality_material_code', table_name='quality_materials', schema='quality')
    op.drop_index('ix_quality_material_name', table_name='quality_materials', schema='quality')
    op.drop_table('quality_materials', schema='quality')
