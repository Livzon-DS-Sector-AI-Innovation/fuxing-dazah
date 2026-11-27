"""五金库报废出库并入申领出库全路径 —— 指定审批人列 + 状态对齐领料单

业务改版（2026-11-25）：报废出库与领料单走同一条出库路径——发起自选审批人，
提交即预扣；审批人通过（飞书审批单，或平台「申请单据 → 待审批」点通过）后
进入待出库；仓管点「出库」才实扣。原两级系统内审批（部门主管确认 →
仓储负责人终审）退役。
- 新列：approver_user_id / approver_name（指定审批人）、requested_by_user_id
  （发起人 identity 锚点，创建飞书实例时解析发起人 user_id）、executed_by
  （出库操作人）；
- 状态：与领料单同名同义 draft/pending/approved/issued/rejected/cancelled
  （重建 CHECK 约束）；
- 在途旧单：旧 pending_dept（待部门主管确认）/ pending_final（待终审）
  → pending（待审批，写备注，由所选审批人或持权限者在平台/飞书审批）；
  旧 approved（旧流程终审通过即销账，已实扣）→ issued（已出库）。

Revision ID: 6fda99ea30dd
Revises: o3a5c7e9b1d3
Create Date: 2026-11-25 11:16:38.754886
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6fda99ea30dd"
down_revision: str | None = "o3a5c7e9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"
TABLE = "hardware_scraps"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            nullable=True,
            comment="发起人 identity.users.id（飞书实例发起人锚点）",
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
            "executed_by",
            sa.String(length=100),
            nullable=True,
            comment="出库操作人（仓管，唯一动账点执行者）",
        ),
        schema=SCHEMA,
    )
    # 旧 approved = 终审通过即销账（已实扣）→ 新状态下即已出库
    op.execute(f"update {SCHEMA}.{TABLE} set status = 'issued' where status = 'approved'")
    # 旧两级流程在途单 → 待审批（新规则：所选审批人一次审批）
    op.execute(
        f"update {SCHEMA}.{TABLE} set status = 'pending', "
        "remark = concat_ws('；', nullif(remark, ''), '旧两级流程在途单，已转为待审批') "
        "where status in ('pending_dept', 'pending_final')"
    )
    op.drop_constraint("ck_hardware_scraps_status", TABLE, schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_scraps_status",
        TABLE,
        "status IN ('draft', 'pending', 'approved', 'issued',"
        " 'rejected', 'cancelled')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    # 新 → 旧：待审批回「待部门主管确认」；待出库回「待终审」；已出库回旧
    # 「终审通过即销账」的 approved
    op.execute(f"update {SCHEMA}.{TABLE} set status = 'pending_dept' where status = 'pending'")
    op.execute(f"update {SCHEMA}.{TABLE} set status = 'pending_final' where status = 'approved'")
    op.execute(f"update {SCHEMA}.{TABLE} set status = 'approved' where status = 'issued'")
    op.drop_constraint("ck_hardware_scraps_status", TABLE, schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_scraps_status",
        TABLE,
        "status IN ('draft', 'pending_dept', 'pending_final', 'approved',"
        " 'rejected', 'cancelled')",
        schema=SCHEMA,
    )
    op.drop_column(TABLE, "executed_by", schema=SCHEMA)
    op.drop_column(TABLE, "approver_name", schema=SCHEMA)
    op.drop_column(TABLE, "approver_user_id", schema=SCHEMA)
    op.drop_column(TABLE, "requested_by_user_id", schema=SCHEMA)
