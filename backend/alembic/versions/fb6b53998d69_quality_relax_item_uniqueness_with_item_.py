"""quality relax item uniqueness with item_name

Revision ID: fb6b53998d69
Revises: 489c00777568
Create Date: 2026-09-03 16:41:24.184002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb6b53998d69'
down_revision: Union[str, None] = '489c00777568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    # 真实标准文档中多个子项目可共用同一 SOP 号，唯一键扩为 (sop_no, item_name)
    op.drop_index('uq_quality_std_item_sop', table_name='quality_standard_items', schema='quality')
    op.create_index('uq_quality_std_item_sop', 'quality_standard_items',
                    ['document_id', 'sop_no', 'item_name'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('uq_quality_test_result_task_sop', table_name='quality_test_results', schema='quality')
    op.create_index('uq_quality_test_result_task_sop', 'quality_test_results',
                    ['task_id', 'sop_no', 'item_name'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_quality_std_item_sop', table_name='quality_standard_items', schema='quality')
    op.create_index('uq_quality_std_item_sop', 'quality_standard_items',
                    ['document_id', 'sop_no'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('uq_quality_test_result_task_sop', table_name='quality_test_results', schema='quality')
    op.create_index('uq_quality_test_result_task_sop', 'quality_test_results',
                    ['task_id', 'sop_no'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))
