"""quality add unqualified events ledger

Revision ID: 9aa36d488a32
Revises: 600b219843ca
Create Date: 2026-09-11 12:14:23.861247
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9aa36d488a32'
down_revision: Union[str, None] = '600b219843ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'quality_unqualified_events',
        sa.Column('task_id', sa.Uuid(), nullable=True, comment='关联检验任务，逻辑引用 quality.quality_test_tasks.id'),
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
        sa.Column('batch_number', sa.String(length=100), nullable=False, comment='批号'),
        sa.Column('item_name', sa.String(length=200), nullable=False, comment='项目名称'),
        sa.Column('sop_no', sa.String(length=64), nullable=True, comment='SOP 号'),
        sa.Column('result_value', sa.Float(), nullable=True, comment='实测值'),
        sa.Column('standard_text', sa.String(length=300), nullable=True, comment='合格标准原文'),
        sa.Column('limit_text', sa.String(length=100), nullable=True, comment='限度摘要（如 ≤ 3.0%）'),
        sa.Column('source', sa.String(length=20), server_default='manual', nullable=False, comment='来源：manual 机器人填报 / web 网页端 / parse 液相解析'),
        sa.Column('handled', sa.Boolean(), server_default='false', nullable=False, comment='是否已人工处理'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_unqualified_event_batch', 'quality_unqualified_events', ['batch_number'], unique=False, schema='quality')
    op.create_index('ix_quality_unqualified_event_task', 'quality_unqualified_events', ['task_id'], unique=False, schema='quality')


def downgrade() -> None:
    op.drop_index('ix_quality_unqualified_event_task', table_name='quality_unqualified_events', schema='quality')
    op.drop_index('ix_quality_unqualified_event_batch', table_name='quality_unqualified_events', schema='quality')
    op.drop_table('quality_unqualified_events', schema='quality')
