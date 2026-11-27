"""qa coa copy links

COA「复制到其它模板」的来源关系：目标记录的一格来自哪条记录的哪一格。
同一目标格只留最新一条（唯一索引）；只写不展示，记录作废后也不动。

Revision ID: eb6a6a5d40b1
Revises: 3ead528832f8
Create Date: 2026-11-26 16:11:58.760206
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb6a6a5d40b1'
down_revision: str | None = '3ead528832f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('coa_copy_links',
    sa.Column('source_report_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_reports.id（来源记录）'),
    sa.Column('target_report_id', sa.Uuid(), nullable=False, comment='逻辑引用 qa.coa_reports.id（目标记录）'),
    sa.Column('kind', sa.String(length=8), nullable=False, comment='batch/item'),
    sa.Column('source_key', sa.String(length=64), nullable=False, comment='来源格：批次字段键 或 来源项目 id'),
    sa.Column('target_key', sa.String(length=64), nullable=False, comment='目标格：批次字段键 或 目标项目 id'),
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
    op.create_check_constraint(
        'ck_qa_coa_copy_links_kind', 'coa_copy_links',
        "kind IN ('batch', 'item')", schema='qa',
    )
    op.create_index('ix_qa_coa_copy_links_source', 'coa_copy_links', ['source_report_id'], unique=False, schema='qa')
    op.create_index('uq_qa_coa_copy_links_target', 'coa_copy_links', ['target_report_id', 'kind', 'target_key'], unique=True, schema='qa')


def downgrade() -> None:
    op.drop_index('uq_qa_coa_copy_links_target', table_name='coa_copy_links', schema='qa')
    op.drop_index('ix_qa_coa_copy_links_source', table_name='coa_copy_links', schema='qa')
    op.drop_constraint('ck_qa_coa_copy_links_kind', 'coa_copy_links', type_='check', schema='qa')
    op.drop_table('coa_copy_links', schema='qa')
