"""qa coa: 标准级批次信息字段覆盖表（稀疏，仅差异模板有行）

Revision ID: a1f3c8d5e7b2
Revises: 7c4e9ab1d2f0
Create Date: 2026-11-17 20:05:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1f3c8d5e7b2'
down_revision: str | None = '7c4e9ab1d2f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('coa_standard_fields',
    sa.Column('standard_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_standards.id'),
    sa.Column('key', sa.String(length=64), nullable=False, comment='字段键（标准内唯一），如 retest_date'),
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
    sa.CheckConstraint("field_type IN ('text', 'date')", name='ck_qa_coa_std_fields_field_type'),
    schema='qa'
    )
    op.create_index('ix_qa_coa_std_fields_standard', 'coa_standard_fields', ['standard_id', 'sort_order'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_std_fields_standard_key', 'coa_standard_fields', ['standard_id', 'key'], unique=True, schema='qa', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_qa_coa_std_fields_standard_key', table_name='coa_standard_fields', schema='qa')
    op.drop_index('ix_qa_coa_std_fields_standard', table_name='coa_standard_fields', schema='qa')
    op.drop_table('coa_standard_fields', schema='qa')
