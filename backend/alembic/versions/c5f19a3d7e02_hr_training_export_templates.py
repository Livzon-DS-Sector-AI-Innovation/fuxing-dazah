"""hr 培训导出模板用户自维护（版本化）

新表 hr.training_export_templates：培训导出 docx 模板的自定义版本
（template_key 对应 training_template_registry 注册项；换传升版本、
旧行保留可回滚激活；当前版唯一部分索引；无当前版时生成器回退
backend/assets/hr/ 仓库默认模板）。不带外键约束（仓库惯例）。

Revision ID: c5f19a3d7e02
Revises: d2f7a94c6e18
Create Date: 2026-11-26 12:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5f19a3d7e02'
down_revision: str | None = 'd2f7a94c6e18'
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = 'hr'
TABLE = 'training_export_templates'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column('template_key', sa.String(length=64), nullable=False, comment='模板注册键（training_template_registry）'),
        sa.Column('version_no', sa.Integer(), nullable=False, comment='版本号（1 起算）'),
        sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False,
                  comment='是否当前使用版本（false=历史版或已被恢复默认）'),
        sa.Column('storage_key', sa.String(length=255), nullable=False, comment='对象存储 key'),
        sa.Column('file_name', sa.String(length=255), nullable=False, comment='展示/下载文件名（用户上传时的文件名）'),
        sa.Column('content_type', sa.String(length=64), server_default=DOCX_MIME, nullable=False, comment='MIME 类型'),
        sa.Column('size', sa.Integer(), nullable=False, comment='文件大小（字节）'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        *_base_columns(),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_training_tpl_key', TABLE, ['template_key'], unique=False, schema=SCHEMA)
    op.create_index(
        'uq_training_tpl_current', TABLE, ['template_key'],
        unique=True, schema=SCHEMA, postgresql_where=sa.text('is_current = true AND is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index('uq_training_tpl_current', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_training_tpl_key', table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
