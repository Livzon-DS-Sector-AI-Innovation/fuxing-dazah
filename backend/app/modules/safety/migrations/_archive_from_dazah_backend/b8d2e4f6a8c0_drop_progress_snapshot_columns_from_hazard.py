"""drop progress snapshot/count columns from hazard_reports

Revision ID: b8d2e4f6a8c0
Revises: a7c0d1e2f3a4
Create Date: 2026-08-12

移除旧的「每日快照/计数」机制字段：
  - last_progress_snapshot：上次督办计算时的进展快照
  - no_progress_days：进展连续未更新天数

「未更新进展」改为仅在通报时依据 progress_note_updated_at 距今天数判断，
不再需要每日快照/计数器。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d2e4f6a8c0'
down_revision: str | None = 'a7c0d1e2f3a4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("hazard_reports", "no_progress_days", schema="safety")
    op.drop_column("hazard_reports", "last_progress_snapshot", schema="safety")


def downgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "last_progress_snapshot", sa.Text(), nullable=True,
            comment="上次督办计算时的进展快照（用于对比是否更新）",
        ),
        schema="safety",
    )
    op.add_column(
        "hazard_reports",
        sa.Column(
            "no_progress_days", sa.Integer(), nullable=True,
            comment="进展连续未更新天数（每日督办计算 +1，进展变更清零）",
        ),
        schema="safety",
    )
