"""qa coa render records

COA 生成留档：每生成（下载）一次 COA 记一行——系统原件（存储键/摘要）与
当时写进模板的值快照。只增不改不删，报告事后被编辑或作废都不动这行。

Revision ID: 3ead528832f8
Revises: 3371249cf36d
Create Date: 2026-11-25 14:59:32.940130
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3ead528832f8'
down_revision: str | None = '3371249cf36d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ### qa COA 生成留档 1 张表（autogenerate 草稿已裁剪无关漂移） ###
    op.create_table('coa_render_records',
    sa.Column('report_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_reports.id（报告作废后仍保留）'),
    sa.Column('product_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_products.id'),
    sa.Column('standard_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_standards.id'),
    sa.Column('standard_code', sa.String(length=64), nullable=False, comment='生成时的模板编号（快照）'),
    sa.Column('batch_no', sa.String(length=64), nullable=False, comment='生成时的批号（快照；验真按它找留档）'),
    sa.Column('filename', sa.String(length=255), nullable=False, comment='交给用户的文件名'),
    sa.Column('file_key', sa.String(length=255), nullable=False, comment='原件存储键（QA 文件存储）'),
    sa.Column('file_sha256', sa.String(length=64), nullable=False, comment='原件摘要；与送出的字节一一对应'),
    sa.Column('template_sha256', sa.String(length=64), nullable=True, comment='所用模板的摘要'),
    sa.Column('values_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='当时写进模板的内容：字段 → 登记值 → 各数据位的写入文字'),
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
    op.create_index('ix_qa_coa_render_batch', 'coa_render_records', ['batch_no'], unique=False, schema='qa')
    op.create_index('ix_qa_coa_render_report', 'coa_render_records', ['report_id', 'created_at'], unique=False, schema='qa')
    op.create_index('ix_qa_coa_render_sha256', 'coa_render_records', ['file_sha256'], unique=False, schema='qa')


def downgrade() -> None:
    op.drop_index('ix_qa_coa_render_sha256', table_name='coa_render_records', schema='qa')
    op.drop_index('ix_qa_coa_render_report', table_name='coa_render_records', schema='qa')
    op.drop_index('ix_qa_coa_render_batch', table_name='coa_render_records', schema='qa')
    op.drop_table('coa_render_records', schema='qa')
