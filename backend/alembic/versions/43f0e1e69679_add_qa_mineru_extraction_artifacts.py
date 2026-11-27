"""add QA MinerU extraction state and artifacts

Revision ID: 43f0e1e69679
Revises: fde16f392af2
Create Date: 2026-09-28 09:47:09.790948
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.schema import SchemaItem

from alembic import op

revision: str = "43f0e1e69679"
down_revision: str | None = "fde16f392af2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.add_column(
        "document_extraction_runs",
        sa.Column("provider", sa.String(32), server_default="native", nullable=False, comment="正文提取后端（native/mineru）"),
        schema="qa",
    )
    op.add_column(
        "document_extraction_runs",
        sa.Column("provider_task_id", sa.String(128), nullable=True, comment="远程提取后端任务 ID"),
        schema="qa",
    )
    op.add_column(
        "document_extraction_runs",
        sa.Column("provider_state", sa.String(32), nullable=True, comment="远程提取后端状态快照"),
        schema="qa",
    )
    op.add_column(
        "document_extraction_runs",
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True, comment="下一次远程状态轮询时间"),
        schema="qa",
    )
    op.add_column(
        "document_extraction_runs",
        sa.Column("provider_context", sa.JSON(), nullable=True, comment="远程任务续跑上下文（不含 token）"),
        schema="qa",
    )
    op.create_table(
        "document_extraction_artifacts",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False, comment="markdown/zip/structure/asset"),
        sa.Column("source_name", sa.String(512), nullable=False, comment="产物在 MinerU ZIP 中的原始路径"),
        sa.Column("storage_key", sa.String(768), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True, comment="解析产物元数据"),
        *_base_columns(),
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_extraction_artifacts_file",
        "document_extraction_artifacts",
        ["file_id", "created_at"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_extraction_artifacts_run",
        "document_extraction_artifacts",
        ["extraction_run_id", "artifact_type"],
        schema="qa",
    )
    op.create_index(
        "uq_qa_document_extraction_artifacts_key",
        "document_extraction_artifacts",
        ["storage_key"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_qa_document_extraction_artifacts_key",
        table_name="document_extraction_artifacts",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_extraction_artifacts_run",
        table_name="document_extraction_artifacts",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_extraction_artifacts_file",
        table_name="document_extraction_artifacts",
        schema="qa",
    )
    op.drop_table("document_extraction_artifacts", schema="qa")
    for name in ("provider_context", "next_poll_at", "provider_state", "provider_task_id", "provider"):
        op.drop_column("document_extraction_runs", name, schema="qa")
