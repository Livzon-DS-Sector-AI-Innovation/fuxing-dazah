"""add progress_note_updated_at to hazard_reports

Revision ID: a7c0d1e2f3a4
Revises: 17f3688ba6e7
Create Date: 2026-08-12

为「目前进展」字段新增最后更新时间戳：
  - progress_note_updated_at：目前进展最后更新时间（Bitable 同步落库时刻，进展内容变化时记录）
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c0d1e2f3a4'
down_revision: str | None = '17f3688ba6e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "progress_note_updated_at", sa.DateTime(timezone=True), nullable=True,
            comment="目前进展最后更新时间（Bitable 同步落库时刻，进展内容变化时记录）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "progress_note_updated_at", schema="safety")
