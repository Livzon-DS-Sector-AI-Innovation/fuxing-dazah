"""qa coa: 产品级批次信息字段配置表（模板导入结构提取的落点）

Revision ID: 7c4e9ab1d2f0
Revises: 389529687153
Create Date: 2026-11-17 18:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c4e9ab1d2f0'
down_revision: str | None = '389529687153'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('coa_product_fields',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_products.id'),
    sa.Column('key', sa.String(length=64), nullable=False, comment='字段键（产品内唯一，阶段二提取 schema 锚点），如 retest_date'),
    sa.Column('label_cn', sa.String(length=100), nullable=False, comment='字段中文标签，如 复验期'),
    sa.Column('label_en', sa.String(length=200), nullable=True, comment='字段英文标签，如 Retest Date'),
    sa.Column('field_type', sa.String(length=8), server_default='text', nullable=False, comment='text/date'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='行顺序'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='停用后阶段二不再渲染该字段'),
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
    sa.CheckConstraint("field_type IN ('text', 'date')", name='ck_qa_coa_fields_field_type'),
    schema='qa'
    )
    op.create_index('ix_qa_coa_fields_product', 'coa_product_fields', ['product_id', 'sort_order'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_fields_product_key', 'coa_product_fields', ['product_id', 'key'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_qa_coa_fields_product_key', table_name='coa_product_fields', schema='qa')
    op.drop_index('ix_qa_coa_fields_product', table_name='coa_product_fields', schema='qa')
    op.drop_table('coa_product_fields', schema='qa')
