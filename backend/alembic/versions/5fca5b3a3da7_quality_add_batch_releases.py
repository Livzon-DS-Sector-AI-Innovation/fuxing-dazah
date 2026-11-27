"""quality add batch releases

Revision ID: 5fca5b3a3da7
Revises: b092cc1c9293
Create Date: 2026-10-28 14:32:00.465046
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5fca5b3a3da7'
down_revision: str | None = 'b092cc1c9293'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        "quality_batch_releases",
        sa.Column("batch_no", sa.String(length=100), nullable=False, comment="批号"),
        sa.Column("product_name", sa.String(length=200), nullable=False, comment="产品名称"),
        sa.Column("task_id", sa.Uuid(), nullable=True, comment="关联检验任务（逻辑引用）"),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="发起时检验汇总快照（判定/复核/报告单/留样）"),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False, comment="pending 待放行 / released 已放行 / void 已作废"),
        sa.Column("released_by", sa.Uuid(), nullable=True, comment="放行人"),
        sa.Column("released_at", sa.String(length=32), nullable=True, comment="放行日期 YYYY-MM-DD"),
        sa.Column("release_remark", sa.String(length=200), nullable=True, comment="放行备注"),
        sa.Column("remark", sa.String(length=200), nullable=True, comment="备注"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"], ),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        schema="quality",
    )
    op.create_index("ix_quality_release_batch", "quality_batch_releases", ["batch_no"], unique=False, schema="quality")
    op.create_index("ix_quality_release_status", "quality_batch_releases", ["status"], unique=False, schema="quality")


def downgrade() -> None:
    op.drop_index("ix_quality_release_status", table_name="quality_batch_releases", schema="quality")
    op.drop_index("ix_quality_release_batch", table_name="quality_batch_releases", schema="quality")
    op.drop_table("quality_batch_releases", schema="quality")
