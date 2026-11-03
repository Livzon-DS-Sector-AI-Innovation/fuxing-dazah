"""新增反馈截图表 feedback.feedback_attachments

反馈支持附带截图（PNG/JPG/WEBP/GIF，单张 ≤5MB，每条最多 3 张）：文件本体落
对象存储（MinIO 的 dazah-feedback bucket，或本地 UPLOAD_DIR/feedback 回退），
本表只存元数据与 sha256。feedback schema 已由上一迁移创建。
autogenerate 夹带的其他模块漂移已按惯例剔除，仅保留本表 DDL。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f8d7b28b55e'
down_revision: str | None = '3e1cdedc0db4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('feedback_attachments',
    sa.Column('feedback_id', sa.Uuid(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by_name', sa.String(length=128), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='feedback'
    )
    op.create_index('ix_feedback_attachments_feedback', 'feedback_attachments', ['feedback_id'], unique=False, schema='feedback')


def downgrade() -> None:
    op.drop_index('ix_feedback_attachments_feedback', table_name='feedback_attachments', schema='feedback')
    op.drop_table('feedback_attachments', schema='feedback')
