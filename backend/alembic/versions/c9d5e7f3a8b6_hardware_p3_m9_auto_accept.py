"""五金库三期 M9 —— receipts 自动入账审计两列（auto_accepted + auto_accept_snapshot）

设计 docs/DESIGN-五金库系统原生模块-20261104.md §9.3 observe→auto 阶段1：
direct 类高置信 OCR 直接入账（默认关）。审计红线：自动入账单落
auto_accepted 标记 + 触发快照（开关来源/阈值/行置信度列表/初筛标记数/
评估决策），周报披露+人工复核抽检入口依赖此列。

Revision ID: c9d5e7f3a8b6
Revises: b8c4d6e2f7a3
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d5e7f3a8b6"
down_revision: str | None = "b8c4d6e2f7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.add_column(
        "hardware_receipts",
        sa.Column("auto_accepted", sa.Boolean(), nullable=False, server_default="false",
                  comment="M9 自动入账标记（direct 高置信；默认全 false）"),
        schema=SCHEMA,
    )
    op.add_column(
        "hardware_receipts",
        sa.Column("auto_accept_snapshot", postgresql.JSONB(), nullable=True,
                  comment="自动入账触发快照 {switch_source, threshold, row_scores[],"
                          " screening_flagged, decision, evaluated_at}"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_receipts_auto_accepted", "hardware_receipts", ["auto_accepted"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hardware_receipts_auto_accepted", table_name="hardware_receipts", schema=SCHEMA,
    )
    op.drop_column("hardware_receipts", "auto_accept_snapshot", schema=SCHEMA)
    op.drop_column("hardware_receipts", "auto_accepted", schema=SCHEMA)
