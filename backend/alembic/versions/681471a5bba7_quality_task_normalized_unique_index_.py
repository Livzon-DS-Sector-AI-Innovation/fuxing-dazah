"""quality: task normalized unique index + standard_document_ids

Revision ID: 681471a5bba7
Revises: b0262fe5b80f
Create Date: 2026-09-28 11:16:25.668353
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '681471a5bba7'
down_revision: Union[str, None] = 'b0262fe5b80f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 任务快照的标准文件 ID 列表（COA 逐份生成的文档集合冗余存储）
    op.add_column(
        'quality_test_tasks',
        sa.Column(
            'standard_document_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='任务快照的标准文件 ID 列表（多选建任务时冗余存储，COA 逐份生成/跳过提示用）',
        ),
        schema='quality',
    )
    # 归一化唯一索引：产品名忽略空白差异，与应用层查重同口径（防并发绕过）
    op.create_index(
        'uq_quality_test_task_norm_product_batch',
        'quality_test_tasks',
        [sa.literal_column("regexp_replace(product_name, '\\s', '', 'g')"), 'batch_number'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_quality_test_task_norm_product_batch',
        table_name='quality_test_tasks',
        schema='quality',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_column('quality_test_tasks', 'standard_document_ids', schema='quality')
