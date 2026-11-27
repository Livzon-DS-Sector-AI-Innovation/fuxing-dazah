"""qa apr 年度产品审核六张表

Revision ID: ba295b00e29e
Revises: a0c4d16f0202
Create Date: 2026-11-05 16:33:00.781080
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ba295b00e29e'
down_revision: Union[str, None] = 'a0c4d16f0202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('apr_annual_reviews',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_products.id'),
    sa.Column('year', sa.Integer(), nullable=False, comment='年度'),
    sa.Column('status', sa.String(length=16), server_default='open', nullable=False, comment='open/locked'),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True, comment='锁定时间'),
    sa.Column('locked_by', sa.Uuid(), nullable=True, comment='锁定人（逻辑引用 identity.users.id）'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("status IN ('open', 'locked')", name='ck_qa_apr_annual_reviews_status'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('uq_qa_apr_annual_reviews_product_year', 'apr_annual_reviews', ['product_id', 'year'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('apr_batches',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_products.id'),
    sa.Column('section_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_sections.id'),
    sa.Column('year', sa.Integer(), nullable=False, comment='所属年度（年终汇总切片键；批号本身跨年）'),
    sa.Column('batch_no', sa.String(length=64), nullable=False, comment='批号，如 DT2402001 / KA-ET-2017-001'),
    sa.Column('seq', sa.Integer(), nullable=True, comment='段内序号（Excel 序号列；空则按创建序）'),
    sa.Column('parent_batch_id', sa.Uuid(), nullable=True, comment='可选血缘：上一段批次（发酵批→种子批）'),
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
    schema='qa'
    )
    op.create_index('ix_qa_apr_batches_product', 'apr_batches', ['product_id'], unique=False, schema='qa')
    op.create_index('ix_qa_apr_batches_section_year', 'apr_batches', ['section_id', 'year'], unique=False, schema='qa')
    op.create_index('uq_qa_apr_batches_section_year_no', 'apr_batches', ['section_id', 'year', 'batch_no'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('apr_items',
    sa.Column('section_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_sections.id'),
    sa.Column('code', sa.String(length=64), nullable=False, comment='段内稳定标识，导出列匹配/趋势接口用'),
    sa.Column('group_name', sa.String(length=100), nullable=True, comment='表头第一层分组，如 解吸/脱钙/纳滤'),
    sa.Column('category', sa.String(length=8), server_default='test', nullable=False, comment='cpp/ipc/test/info'),
    sa.Column('name_cn', sa.String(length=200), nullable=False, comment='名称（中文）'),
    sa.Column('name_en', sa.String(length=200), nullable=True, comment='名称（英文）'),
    sa.Column('value_type', sa.String(length=8), server_default='number', nullable=False, comment='number/text'),
    sa.Column('unit', sa.String(length=32), nullable=True, comment='单位：℃/rpm/EU/mg/ppm 等'),
    sa.Column('spec_text', sa.String(length=200), nullable=True, comment='标准原文，如 4.0-4.6 / ≤5.0% / 无杂菌生长'),
    sa.Column('spec_min', sa.Float(), nullable=True, comment='标准下限；只有 min 即 ≥，双值即区间'),
    sa.Column('spec_max', sa.Float(), nullable=True, comment='标准上限；只有 max 即 ≤'),
    sa.Column('oot_min', sa.Float(), nullable=True, comment='OOT 预警下限（通常比标准限窄，人工设定）'),
    sa.Column('oot_max', sa.Float(), nullable=True, comment='OOT 预警上限'),
    sa.Column('trend_enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否纳入趋势图；文字项应设 false'),
    sa.Column('required', sa.Boolean(), server_default='false', nullable=False, comment='是否必填'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='停用后不可再录入'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='列顺序'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("category IN ('cpp', 'ipc', 'test', 'info')", name='ck_qa_apr_items_category'),
    sa.CheckConstraint("value_type IN ('number', 'text')", name='ck_qa_apr_items_value_type'),
    sa.CheckConstraint('oot_min IS NULL OR oot_max IS NULL OR oot_min <= oot_max', name='ck_qa_apr_items_oot_range'),
    sa.CheckConstraint('spec_min IS NULL OR spec_max IS NULL OR spec_min <= spec_max', name='ck_qa_apr_items_spec_range'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('ix_qa_apr_items_section', 'apr_items', ['section_id', 'sort_order'], unique=False, schema='qa')
    op.create_index('uq_qa_apr_items_section_code', 'apr_items', ['section_id', 'code'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('apr_products',
    sa.Column('code', sa.String(length=32), nullable=False, comment='产品短码（批号前缀来源），如 DT/KA/ST'),
    sa.Column('name', sa.String(length=100), nullable=False, comment='产品中文名'),
    sa.Column('name_en', sa.String(length=100), nullable=True, comment='产品英文名'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
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
    schema='qa'
    )
    op.create_index('uq_qa_apr_products_code', 'apr_products', ['code'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('apr_sections',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_products.id'),
    sa.Column('name', sa.String(length=100), nullable=False, comment='段名，如 菌种-摇瓶培养 / 成品检验-USP'),
    sa.Column('data_kind', sa.String(length=16), server_default='production', nullable=False, comment='production/inspection'),
    sa.Column('market', sa.String(length=16), nullable=True, comment='市场/药典：US/EP/Ch.P，仅检验段有'),
    sa.Column('stage', sa.String(length=32), nullable=True, comment='工序阶段短码：seed/fermentation/extraction/finished_test'),
    sa.Column('multi_row', sa.Boolean(), server_default='false', nullable=False, comment='一批是否多行（多罐/续行），默认 false'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='段顺序'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("data_kind IN ('production', 'inspection')", name='ck_qa_apr_sections_data_kind'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('ix_qa_apr_sections_product', 'apr_sections', ['product_id', 'sort_order'], unique=False, schema='qa')
    op.create_table('apr_values',
    sa.Column('batch_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_batches.id'),
    sa.Column('item_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.apr_items.id'),
    sa.Column('row_seq', sa.Integer(), server_default='1', nullable=False, comment='行号；multi_row 段的 1/2/3…'),
    sa.Column('row_label', sa.String(length=32), nullable=True, comment='行标签，如 1号罐'),
    sa.Column('value_num', sa.Float(), nullable=True, comment='数值型结果'),
    sa.Column('value_text', sa.String(length=300), nullable=True, comment='文字判定/半定量：符合规定/未检出/<1/N/A'),
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
    schema='qa'
    )
    op.create_index('ix_qa_apr_values_batch', 'apr_values', ['batch_id'], unique=False, schema='qa')
    op.create_index('ix_qa_apr_values_item', 'apr_values', ['item_id'], unique=False, schema='qa')
    op.create_index('uq_qa_apr_values_batch_item_row', 'apr_values', ['batch_id', 'item_id', 'row_seq'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))

def downgrade() -> None:
    op.drop_index('uq_qa_apr_values_batch_item_row', table_name='apr_values', schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_qa_apr_values_item', table_name='apr_values', schema='qa')
    op.drop_index('ix_qa_apr_values_batch', table_name='apr_values', schema='qa')
    op.drop_table('apr_values', schema='qa')
    op.drop_index('ix_qa_apr_sections_product', table_name='apr_sections', schema='qa')
    op.drop_table('apr_sections', schema='qa')
    op.drop_index('uq_qa_apr_products_code', table_name='apr_products', schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('apr_products', schema='qa')
    op.drop_index('uq_qa_apr_items_section_code', table_name='apr_items', schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_qa_apr_items_section', table_name='apr_items', schema='qa')
    op.drop_table('apr_items', schema='qa')
    op.drop_index('uq_qa_apr_batches_section_year_no', table_name='apr_batches', schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_qa_apr_batches_section_year', table_name='apr_batches', schema='qa')
    op.drop_index('ix_qa_apr_batches_product', table_name='apr_batches', schema='qa')
    op.drop_table('apr_batches', schema='qa')
    op.drop_index('uq_qa_apr_annual_reviews_product_year', table_name='apr_annual_reviews', schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('apr_annual_reviews', schema='qa')
