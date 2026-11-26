"""hr.training_export_templates.content_type 列宽 64 → 100

docx 的 MIME 串（application/vnd.openxmlformats-officedocument.wordprocessingml.document）
有 71 字符，超出原 varchar(64)。列宽放宽到 100（存 MIME 的常规上限）。

Revision ID: b6e04c8f12a7
Revises: a3e8b1c4f7d2
Create Date: 2026-11-26 15:30:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b6e04c8f12a7'
down_revision: str | None = 'a3e8b1c4f7d2'
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = 'hr'
TABLE = 'training_export_templates'


def upgrade() -> None:
    op.alter_column(
        TABLE, 'content_type',
        existing_type=sa.String(length=64), type_=sa.String(length=100),
        existing_nullable=False, schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        TABLE, 'content_type',
        existing_type=sa.String(length=100), type_=sa.String(length=64),
        existing_nullable=False, schema=SCHEMA,
    )
