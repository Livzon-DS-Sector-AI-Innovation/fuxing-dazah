"""quality add suppliers and material vendor_code

Revision ID: 295241149973
Revises: c6648fa4d9d0
Create Date: 2026-10-12 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '295241149973'
down_revision: Union[str, None] = 'c6648fa4d9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_suppliers',
    sa.Column('code', sa.String(length=100), nullable=False, comment='供应商代码'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='供应商名称'),
    sa.Column('contact', sa.String(length=100), nullable=True, comment='联系人'),
    sa.Column('phone', sa.String(length=50), nullable=True, comment='联系电话'),
    sa.Column('qual_expiry_date', sa.String(length=32), nullable=True, comment='资质效期 YYYY-MM-DD（到期提醒）'),
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
    op.create_index('ix_quality_supplier_name', 'quality_suppliers', ['name'], unique=False, schema='quality')
    op.create_index('uq_quality_supplier_code', 'quality_suppliers', ['code'], unique=True, schema='quality', postgresql_where=sa.text('is_deleted = false'))
    op.add_column('quality_materials', sa.Column('vendor_code', sa.String(length=100), nullable=True, comment='供应商代码（逻辑引用 quality.quality_suppliers.code）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_materials', 'vendor_code', schema='quality')
    op.drop_index('uq_quality_supplier_code', table_name='quality_suppliers', schema='quality')
    op.drop_index('ix_quality_supplier_name', table_name='quality_suppliers', schema='quality')
    op.drop_table('quality_suppliers', schema='quality')
