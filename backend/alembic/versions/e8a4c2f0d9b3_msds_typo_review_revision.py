"""safety msds_documents 错别字审核 + 修订同步字段

MSDS 错别字审核机制（AI 校对只标记，人工在台账表裁决修订）+ 修订机制
（内容字段修改 → 标准 PDF 自动同步重生成）配套列：
- typo_review_status / typo_review_detail：AI 校对结果镜像；
- revision_log：修订→PDF 同步日志（最近 20 行）；
- pdf_content_hash：PDF 生成时内容 hash（同步判定，不一致才重生成附件）。

Revision ID: e8a4c2f0d9b3
Revises: c3d5e7f9a1b2
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a4c2f0d9b3"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column(
        "typo_review_status", sa.String(length=16), nullable=False,
        server_default="未审核",
        comment="错别字审核: 未审核/无错别字/疑似错别字（AI 校对只标记，人工裁决）",
    ),
    sa.Column(
        "typo_review_detail", sa.Text(), nullable=True,
        comment="错别字明细（字段名：『原文』→『建议』（类型），一行一条）",
    ),
    sa.Column(
        "revision_log", sa.Text(), nullable=True,
        comment="修订记录（字段修改→PDF 同步重生成日志，最近 20 行）",
    ),
    sa.Column(
        "pdf_content_hash", sa.String(length=64), nullable=True,
        comment="标准 PDF 生成时的内容字段 hash（修订同步判定：不一致才重生成附件）",
    ),
)


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("msds_documents", col, schema="safety")


def downgrade() -> None:
    for name in ("pdf_content_hash", "revision_log", "typo_review_detail", "typo_review_status"):
        op.drop_column("msds_documents", name, schema="safety")
