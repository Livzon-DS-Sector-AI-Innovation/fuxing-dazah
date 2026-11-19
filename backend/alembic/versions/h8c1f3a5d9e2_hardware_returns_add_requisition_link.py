"""五金库退料货对板校验 —— 退库单加关联领料实例列

飞书退料审批改版（2026-11-19 拍板）：退料须选关联领料审批，发起时系统
校验物料∈关联领料明细、逐料 退量 ≤ 领量−已退量，违者拒收+退回审批。
本列=校验锚点（关联领料单的 approval_instance_code；系统内建退库单恒 NULL），
也是「已退量」累计的圈定键。

Revision ID: h8c1f3a5d9e2
Revises: g5b7d9f1e3c4
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h8c1f3a5d9e2"
down_revision: str | None = "g5b7d9f1e3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.add_column(
        "hardware_returns",
        sa.Column(
            "requisition_instance_code",
            sa.String(length=100),
            nullable=True,
            comment="关联领料审批实例 code（退料货对板校验锚点；系统内建退库单为 NULL）",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_returns_requisition_instance_code",
        "hardware_returns",
        ["requisition_instance_code"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hardware_returns_requisition_instance_code",
        table_name="hardware_returns",
        schema=SCHEMA,
    )
    op.drop_column("hardware_returns", "requisition_instance_code", schema=SCHEMA)
