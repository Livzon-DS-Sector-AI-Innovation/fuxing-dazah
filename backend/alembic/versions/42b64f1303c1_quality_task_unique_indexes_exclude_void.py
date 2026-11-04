"""quality: task unique indexes exclude void

作废任务不占批号，允许同批号重建任务：两个唯一索引排除 void。

Revision ID: 42b64f1303c1
Revises: 681471a5bba7
Create Date: 2026-09-30 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '42b64f1303c1'
down_revision: Union[str, None] = '681471a5bba7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('uq_quality_test_task_product_batch', table_name='quality_test_tasks', schema='quality')
    op.drop_index('uq_quality_test_task_norm_product_batch', table_name='quality_test_tasks', schema='quality')
    op.create_index(
        'uq_quality_test_task_product_batch',
        'quality_test_tasks',
        ['product_name', 'batch_number'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text("is_deleted = false AND status <> 'void'"),
    )
    op.create_index(
        'uq_quality_test_task_norm_product_batch',
        'quality_test_tasks',
        [sa.literal_column("regexp_replace(product_name, '\\s', '', 'g')"), 'batch_number'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text("is_deleted = false AND status <> 'void'"),
    )


def downgrade() -> None:
    op.drop_index('uq_quality_test_task_product_batch', table_name='quality_test_tasks', schema='quality')
    op.drop_index('uq_quality_test_task_norm_product_batch', table_name='quality_test_tasks', schema='quality')
    op.create_index(
        'uq_quality_test_task_product_batch',
        'quality_test_tasks',
        ['product_name', 'batch_number'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_index(
        'uq_quality_test_task_norm_product_batch',
        'quality_test_tasks',
        [sa.literal_column("regexp_replace(product_name, '\\s', '', 'g')"), 'batch_number'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text('is_deleted = false'),
    )
