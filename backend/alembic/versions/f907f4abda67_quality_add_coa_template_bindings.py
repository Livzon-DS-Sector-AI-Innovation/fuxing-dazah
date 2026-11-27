"""quality add coa template bindings

Revision ID: f907f4abda67
Revises: 459df173919d
Create Date: 2026-09-09 10:40:44.097391
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f907f4abda67'
down_revision: Union[str, None] = '459df173919d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        'quality_coa_template_bindings',
        sa.Column('template_path', sa.String(length=500), nullable=False, comment='COA 模板路径（唯一）'),
        sa.Column('standard_document_id', sa.Uuid(), nullable=True, comment='绑定的标准文档'),
        sa.Column('sop_no', sa.String(length=64), nullable=True, comment='绑定的 SOP 号快照（标准文档 file_no）'),
        sa.Column('description', sa.String(length=200), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('uq_quality_coa_binding_template', 'quality_coa_template_bindings',
                    ['template_path'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_quality_coa_binding_doc', 'quality_coa_template_bindings',
                    ['standard_document_id'], unique=False, schema='quality')
    # 迁移既有绑定：标准文档上的 template_path 转为 COA 侧绑定记录
    op.execute(sa.text(
        "INSERT INTO quality.quality_coa_template_bindings "
        "(id, template_path, standard_document_id, sop_no, created_at, updated_at, is_deleted) "
        "SELECT gen_random_uuid(), d.template_path, d.id, d.file_no, now(), now(), false "
        "FROM quality.quality_standard_documents d "
        "WHERE d.template_path IS NOT NULL AND d.is_deleted = false"
    ))



def downgrade() -> None:
    op.drop_table('quality_coa_template_bindings', schema='quality')
