"""qa coa domain: products standards items reports values

Revision ID: 3255fabca2f6
Revises: 9ce7cc860598
Create Date: 2026-11-12 18:54:41.468718
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3255fabca2f6'
down_revision: Union[str, None] = '9ce7cc860598'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### qa COA 域 5 张表（autogenerate 草稿已裁剪无关漂移） ###
    op.create_table('coa_products',
    sa.Column('code', sa.String(length=32), nullable=False, comment='产品短码（批号/COA编号前缀），大写，如 HAF'),
    sa.Column('name', sa.String(length=100), nullable=False, comment='产品中文名'),
    sa.Column('name_en', sa.String(length=200), nullable=True, comment='产品英文名'),
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
    op.create_index('uq_qa_coa_products_code', 'coa_products', ['code'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_qa_coa_products_name', 'coa_products', ['name'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('coa_report_values',
    sa.Column('report_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_reports.id'),
    sa.Column('item_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_standard_items.id'),
    sa.Column('value_num', sa.Float(), nullable=True, comment='数值型结果（按项目 value_type 落列）'),
    sa.Column('value_text', sa.String(length=300), nullable=True, comment='结果原文（永远保留，如 符合规定/＜1cfu/g）'),
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
    op.create_index('ix_qa_coa_values_item', 'coa_report_values', ['item_id'], unique=False, schema='qa')
    op.create_index('ix_qa_coa_values_report', 'coa_report_values', ['report_id'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_values_report_item', 'coa_report_values', ['report_id', 'item_id'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('coa_reports',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_products.id'),
    sa.Column('standard_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_standards.id'),
    sa.Column('report_no', sa.String(length=64), nullable=False, comment='COA 报告编号，如 COA-HAF-3205-006'),
    sa.Column('serial_no', sa.String(length=32), nullable=True, comment='流水号（docx 右上角数字串），如 26081215'),
    sa.Column('batch_no', sa.String(length=64), nullable=False, comment='批号'),
    sa.Column('mfg_date', sa.Date(), nullable=True, comment='生产日期'),
    sa.Column('exp_date', sa.Date(), nullable=True, comment='有效期至'),
    sa.Column('packaging', sa.String(length=100), nullable=True, comment='包装规格，如 5kg/Tin'),
    sa.Column('batch_size', sa.String(length=50), nullable=True, comment='批量，如 41.120kg'),
    sa.Column('storage', sa.String(length=300), nullable=True, comment='贮存条件'),
    sa.Column('conclusion', sa.String(length=500), nullable=True, comment='结论'),
    sa.Column('issued_date', sa.Date(), nullable=True, comment='出具日期（人工填写）'),
    sa.Column('source', sa.String(length=8), server_default='manual', nullable=False, comment='manual/import'),
    sa.Column('raw_extract', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='导入时的原始提取结果（复核/重放用）'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("source IN ('manual', 'import')", name='ck_qa_coa_reports_source'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('ix_qa_coa_reports_product', 'coa_reports', ['product_id', 'issued_date'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_reports_no', 'coa_reports', ['report_no'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_qa_coa_reports_product_standard_batch', 'coa_reports', ['product_id', 'standard_id', 'batch_no'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('coa_standard_items',
    sa.Column('standard_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_standards.id'),
    sa.Column('code', sa.String(length=64), nullable=False, comment='项目稳定标识（名称归一化生成），导入匹配键'),
    sa.Column('group_name', sa.String(length=100), nullable=True, comment='大类分组（docx 纵向合并单元格），如 性状/鉴别'),
    sa.Column('name_cn', sa.String(length=200), nullable=False, comment='项目名（中文）'),
    sa.Column('name_en', sa.String(length=200), nullable=True, comment='项目名（英文）'),
    sa.Column('value_type', sa.String(length=8), server_default='text', nullable=False, comment='number/text'),
    sa.Column('unit', sa.String(length=32), nullable=True, comment='单位：%/ppm/EU/mg 等'),
    sa.Column('spec_text', sa.String(length=200), nullable=True, comment='标准原文：≤3.0% / 2.5～4.5 / 白色粉末（全角原样）'),
    sa.Column('spec_min', sa.Float(), nullable=True, comment='标准下限（导入解析成功才填，仅 ≥ 语义）'),
    sa.Column('spec_max', sa.Float(), nullable=True, comment='标准上限（导入解析成功才填，仅 ≤ 语义）'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='列顺序=docx 原序'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='停用后矩阵不再显示该列'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("value_type IN ('number', 'text')", name='ck_qa_coa_items_value_type'),
    sa.CheckConstraint('spec_min IS NULL OR spec_max IS NULL OR spec_min <= spec_max', name='ck_qa_coa_items_spec_range'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('ix_qa_coa_items_standard', 'coa_standard_items', ['standard_id', 'sort_order'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_items_standard_code', 'coa_standard_items', ['standard_id', 'code'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('coa_standards',
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_products.id'),
    sa.Column('code', sa.String(length=64), nullable=False, comment='模板编号（docx 导入匹配锚点），如 3205'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='标准名称'),
    sa.Column('customer', sa.String(length=200), nullable=True, comment='客户名称'),
    sa.Column('market', sa.String(length=16), nullable=True, comment='市场/药典：USP/EP/ChP'),
    sa.Column('version', sa.String(length=50), nullable=True, comment='版本文字标注（仅展示，不做版本演进）'),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
    sa.Column('source', sa.String(length=8), server_default='manual', nullable=False, comment='manual/import'),
    sa.Column('raw_extract', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='导入来源 docx 的原始提取结果（重放/复核用）'),
    sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.CheckConstraint("source IN ('manual', 'import')", name='ck_qa_coa_standards_source'),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='qa'
    )
    op.create_index('ix_qa_coa_standards_product', 'coa_standards', ['product_id'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_standards_product_code', 'coa_standards', ['product_id', 'code'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_qa_coa_standards_product_code', table_name='coa_standards', schema='qa')
    op.drop_index('ix_qa_coa_standards_product', table_name='coa_standards', schema='qa')
    op.drop_index('uq_qa_coa_items_standard_code', table_name='coa_standard_items', schema='qa')
    op.drop_index('ix_qa_coa_items_standard', table_name='coa_standard_items', schema='qa')
    op.drop_index('uq_qa_coa_reports_product_standard_batch', table_name='coa_reports', schema='qa')
    op.drop_index('uq_qa_coa_reports_no', table_name='coa_reports', schema='qa')
    op.drop_index('ix_qa_coa_reports_product', table_name='coa_reports', schema='qa')
    op.drop_index('uq_qa_coa_values_report_item', table_name='coa_report_values', schema='qa')
    op.drop_index('ix_qa_coa_values_report', table_name='coa_report_values', schema='qa')
    op.drop_index('ix_qa_coa_values_item', table_name='coa_report_values', schema='qa')
    op.drop_index('uq_qa_coa_products_name', table_name='coa_products', schema='qa')
    op.drop_index('uq_qa_coa_products_code', table_name='coa_products', schema='qa')
    op.drop_table('coa_standards', schema='qa')
    op.drop_table('coa_standard_items', schema='qa')
    op.drop_table('coa_reports', schema='qa')
    op.drop_table('coa_report_values', schema='qa')
    op.drop_table('coa_products', schema='qa')
