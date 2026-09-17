"""warehouse reconciliation repair columns

对账裁决反转（V3.0 分期A Ticket 09）：sync_check_results 增加修复状态列
（repair_status/repaired_at），支撑「按 Base 修复本地」人工一键动作与重复修复拒绝。

Revision ID: c9e5a7b3d1f4
Revises: b8d4f2a6c1e9
Create Date: 2026-09-17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e5a7b3d1f4'
down_revision: str | None = 'b8d4f2a6c1e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'sync_check_results',
        sa.Column(
            'repair_status', sa.String(length=16), nullable=True,
            comment='修复状态: repaired=已按Base修复 / manual=待人工处置（V3.0 分期A）',
        ),
        schema='warehouse',
    )
    op.add_column(
        'sync_check_results',
        sa.Column('repaired_at', sa.DateTime(timezone=True), nullable=True, comment='修复时间'),
        schema='warehouse',
    )


def downgrade() -> None:
    op.drop_column('sync_check_results', 'repaired_at', schema='warehouse')
    op.drop_column('sync_check_results', 'repair_status', schema='warehouse')
