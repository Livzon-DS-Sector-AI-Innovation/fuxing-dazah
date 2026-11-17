"""五金库领/退料审批摄取 —— 退库单加审批实例幂等键列

飞书「福兴电子领/退料单审批」实例摄取（approval_ingest）：
- 领料单复用既有 approval_instance_code 列；
- 退库单（hardware_returns）原无审批关联列，补 approval_instance_code
  （飞书退料实例 → 退库草稿的幂等键；系统内建退库单恒 NULL）+ 部分唯一
  索引防重复摄取。

Revision ID: f4a6c8e0d2b3
Revises: a5c7e9b1d3f2  # 2026-11-13 双头消解：原挂 d1e2f4a6b8c5 与 R3 线分叉，改挂 R3 链尾成单链
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a6c8e0d2b3"
down_revision: str | None = "a5c7e9b1d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.add_column(
        "hardware_returns",
        sa.Column(
            "approval_instance_code",
            sa.String(length=100),
            nullable=True,
            comment="飞书领/退料审批实例 code（退料摄取幂等键；系统内建退库单为 NULL）",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_returns_approval_instance_code",
        "hardware_returns",
        ["approval_instance_code"],
        unique=True,
        postgresql_where=sa.text("approval_instance_code IS NOT NULL"),
        schema=SCHEMA,
    )
    # 领料表幂等闸（审查 P1）：领料单复用既有 approval_instance_code 列但
    # 无唯一索引——WS 事件与 reconcile 对账并发摄取时 TOCTOU 可重复建单
    # + 双重预扣，与退库表对齐补部分唯一索引（DB 留痕判定红线）。
    op.create_index(
        "uq_hardware_requisitions_approval_instance_code",
        "hardware_requisitions",
        ["approval_instance_code"],
        unique=True,
        postgresql_where=sa.text("approval_instance_code IS NOT NULL"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # 幂等 drop（IF EXISTS）：dev 库可能以旧版本（无领料索引）应用过本迁移，
    # 双头消解重放时 downgrade 会先于 upgrade 触达新加的索引。
    op.execute(
        "DROP INDEX IF EXISTS warehouse.uq_hardware_requisitions_approval_instance_code"
    )
    op.drop_index(
        "uq_hardware_returns_approval_instance_code",
        table_name="hardware_returns",
        schema=SCHEMA,
    )
    op.drop_column("hardware_returns", "approval_instance_code", schema=SCHEMA)
