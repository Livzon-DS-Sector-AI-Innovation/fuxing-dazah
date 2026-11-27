"""五金库退库单加审批链路列 + 状态扩展（2026-11-26 平台退料功能）

从已发料领料单发起退料：平台填单 → 飞书「五金库退料-平台」分支审批给所选
审批人 → 同意后仓管验收回加（物料回库存）。与飞书自建退料、平台登记退库
共用 hardware_returns 表（approval_channel 为空=老链路，行为不变）。
- 新列：requisition_id（源领料单 id，额度校验锚点）、approver_user_id /
  approver_name（指定审批人）、approval_channel / approval_status、
  rejected_by（驳回人）；
- 状态：draft/pending/approved 加入 CHECK（重建约束）——老 draft 语义不变
  （登记退库的"待签收验收"），平台发起链路 pending=待审批、approved=待验收。

Revision ID: e44c4806a50c
Revises: 21515b6d0561
Create Date: 2026-11-26 08:49:18.364957
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e44c4806a50c"
down_revision: str | None = "21515b6d0561"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"
TABLE = "hardware_returns"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "requisition_id",
            sa.Uuid(),
            nullable=True,
            comment="平台发起：源领料单 id（额度校验锚点；飞书自建/登记退库为 NULL）",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "approver_user_id",
            sa.String(length=100),
            nullable=True,
            comment="指定审批人飞书 user_id（发起人自选，建实例时传节点）",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "approver_name",
            sa.String(length=100),
            nullable=True,
            comment="指定审批人姓名",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "approval_channel",
            sa.String(length=10),
            nullable=True,
            comment="审批通道：feishu（飞书审批单）/ manual（平台点通过）；空=老登记链路",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "approval_status",
            sa.String(length=20),
            nullable=True,
            comment="审批结果映射：pending/approved/rejected/cancelled",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "rejected_by",
            sa.String(length=100),
            nullable=True,
            comment="驳回人（审批驳回/拒退）",
        ),
        schema=SCHEMA,
    )
    op.drop_constraint("ck_hardware_returns_status", TABLE, schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_returns_status",
        TABLE,
        "status IN ('draft', 'pending', 'approved', 'accepted', 'rejected', 'cancelled')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("ck_hardware_returns_status", TABLE, schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_returns_status",
        TABLE,
        "status IN ('draft', 'accepted', 'rejected')",
        schema=SCHEMA,
    )
    op.drop_column(TABLE, "rejected_by", schema=SCHEMA)
    op.drop_column(TABLE, "approval_status", schema=SCHEMA)
    op.drop_column(TABLE, "approval_channel", schema=SCHEMA)
    op.drop_column(TABLE, "approver_name", schema=SCHEMA)
    op.drop_column(TABLE, "approver_user_id", schema=SCHEMA)
    op.drop_column(TABLE, "requisition_id", schema=SCHEMA)
