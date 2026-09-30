"""quality report records task-driven coa

Revision ID: 4973c32c5a76
Revises: 5f25b7332b4b
Create Date: 2026-09-03 14:36:28.618436

P2 任务驱动 COA：report_records.inspection_record_id 改可空（任务驱动的 COA 无检验记录），
新增 test_task_id 关联检验任务。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4973c32c5a76'
down_revision: Union[str, None] = '5f25b7332b4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.alter_column(
        'report_records', 'inspection_record_id',
        existing_type=sa.Uuid(), nullable=True, schema='quality',
    )
    op.add_column(
        'report_records',
        sa.Column('test_task_id', sa.Uuid(), nullable=True,
                  comment='关联检验任务，逻辑引用 quality.quality_test_tasks.id（P2 任务驱动 COA）'),
        schema='quality',
    )


def downgrade() -> None:
    op.drop_column('report_records', 'test_task_id', schema='quality')
    op.alter_column(
        'report_records', 'inspection_record_id',
        existing_type=sa.Uuid(), nullable=False, schema='quality',
    )
