"""add progress monitoring fields to hazard_reports

Revision ID: 17f3688ba6e7
Revises: sched001a2b3c4d
Create Date: 2026-08-11 17:32:58.956352

新增「未更新进展」督办机制所需的 4 个字段：
  - progress_note：目前进展（由 Bitable「目前进展」字段同步）
  - last_progress_snapshot：上次督办计算时的进展快照（对比是否更新）
  - no_progress_days：进展连续未更新天数（每日督办计算 +1，进展变更清零）
  - supervision_progress_status：督办进展状态（未更新进展 / NULL）
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '17f3688ba6e7'
down_revision: str | None = 'sched001a2b3c4d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "progress_note", sa.Text(), nullable=True,
            comment="目前进展（Bitable「目前进展」字段同步，责任人填写的整改进展）",
        ),
        schema="safety",
    )
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
    op.add_column(
        "hazard_reports",
        sa.Column(
            "supervision_progress_status", sa.String(16), nullable=True,
            comment="督办进展状态: 未更新进展 / NULL(正常)",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "supervision_progress_status", schema="safety")
    op.drop_column("hazard_reports", "no_progress_days", schema="safety")
    op.drop_column("hazard_reports", "last_progress_snapshot", schema="safety")
    op.drop_column("hazard_reports", "progress_note", schema="safety")
