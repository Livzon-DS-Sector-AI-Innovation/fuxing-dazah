"""safety chemical_inventory_snapshots 加 source 列（D8 环比断点判定）

sheet 源快照写 'sheet'，legacy/总表口径行保持 NULL；可空列，无默认值、
无回填——判定语义即「NULL=切换前」。down 删列。

Revision ID: c2d6e8f0a4b7
Revises: b7e2f4a9c1d3
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2d6e8f0a4b7"
down_revision: str | None = "b7e2f4a9c1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = ("safety", "chemical_inventory_snapshots")


def upgrade() -> None:
    op.add_column(
        _TABLE[1],
        sa.Column("source", sa.String(length=16), nullable=True,
                  comment="快照数据源(bitable/sheet；NULL=legacy)"),
        schema=_TABLE[0],
    )


def downgrade() -> None:
    op.drop_column(_TABLE[1], "source", schema=_TABLE[0])
