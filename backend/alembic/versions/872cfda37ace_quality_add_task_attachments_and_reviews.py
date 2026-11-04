"""quality add task attachments and reviews

Revision ID: 872cfda37ace
Revises: 411c172d18a3
Create Date: 2026-09-15 16:59:47.477235
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '872cfda37ace'
down_revision: Union[str, None] = '411c172d18a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'quality_task_attachments',
        sa.Column('task_id', sa.Uuid(), nullable=False, comment='关联检验任务，逻辑引用 quality.quality_test_tasks.id'),
        sa.Column('filename', sa.String(length=255), nullable=False, comment='原始文件名'),
        sa.Column('content_type', sa.String(length=100), server_default='application/octet-stream', nullable=False),
        sa.Column('object_key', sa.String(length=500), nullable=False, comment='MinIO 对象键/本地相对路径（attachments/{task_id}/{uuid}_{filename}）'),
        sa.Column('size', sa.Integer(), server_default='0', nullable=False, comment='文件大小（字节）'),
        sa.Column('uploaded_by', sa.Uuid(), nullable=True, comment='上传人，逻辑引用 identity.users.id'),
        sa.Column('source', sa.String(length=20), server_default='manual', nullable=False, comment='来源：manual 人工上传 / parse 液相计算表自动归档'),
        sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_task_attachment_task', 'quality_task_attachments', ['task_id'], unique=False, schema='quality')

    op.create_table(
        'quality_task_reviews',
        sa.Column('task_id', sa.Uuid(), nullable=False, comment='关联检验任务，逻辑引用 quality.quality_test_tasks.id'),
        sa.Column('reviewer_id', sa.Uuid(), nullable=False, comment='复核人，逻辑引用 identity.users.id'),
        sa.Column('comment', sa.String(length=300), nullable=True, comment='复核备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('ix_quality_task_review_task', 'quality_task_reviews', ['task_id'], unique=False, schema='quality')
    op.create_index(
        'uq_quality_task_review_task_reviewer',
        'quality_task_reviews',
        ['task_id', 'reviewer_id'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text('(is_deleted = false)'),
    )


def downgrade() -> None:
    op.drop_index('uq_quality_task_review_task_reviewer', table_name='quality_task_reviews', schema='quality')
    op.drop_index('ix_quality_task_review_task', table_name='quality_task_reviews', schema='quality')
    op.drop_table('quality_task_reviews', schema='quality')
    op.drop_index('ix_quality_task_attachment_task', table_name='quality_task_attachments', schema='quality')
    op.drop_table('quality_task_attachments', schema='quality')
