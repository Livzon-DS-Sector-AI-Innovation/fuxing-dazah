"""五金库紧急领料改版收口 —— 紧急原因列 + 独立紧急链退役（2026-11-20 拍板）

业务改版：紧急领料不再有独立「先发后补」流程，统一在「福兴电子领/退料单审批」
表单上打「是否紧急=是」+「紧急原因」，审批单据本身即闭环手续。紧急单语义收敛为
「仓管可审批前发料（先发后批）」，原补办跟进链全量退役：
- 列：urgent_patch_deadline / patched_at（P1 遗留）、patch_reminders /
  last_overdue_notified_at（i4d6f8a0c2e5）全部删除；
- 状态：overdue_unpatched 从 CHECK 约束移除（重建约束）；
- 推送：hardware_urgent_overdue 任务行删除；
- 新增 urgent_reason（审批表单「紧急原因」控件同源，req_type=urgent 必填）。

Revision ID: o3a5c7e9b1d3
Revises: c3e5a7b9d1f4
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "o3a5c7e9b1d3"
down_revision: str | None = "c3e5a7b9d1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"

_DROP_PATCH_COLUMNS = (
    "urgent_patch_deadline",
    "patched_at",
    "patch_reminders",
    "last_overdue_notified_at",
)


def upgrade() -> None:
    op.add_column(
        "hardware_requisitions",
        sa.Column(
            "urgent_reason",
            sa.String(200),
            nullable=True,
            comment="紧急原因（req_type=urgent 必填，审批表单「紧急原因」同源）",
        ),
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_hardware_requisitions_status",
        "hardware_requisitions",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hardware_requisitions_status",
        "hardware_requisitions",
        "status IN ('draft', 'pending', 'approved', 'issued', 'rejected', 'cancelled')",
        schema=SCHEMA,
    )
    for col in _DROP_PATCH_COLUMNS:
        op.drop_column("hardware_requisitions", col, schema=SCHEMA)
    op.execute(
        "DELETE FROM warehouse.push_tasks WHERE task_name = 'hardware_urgent_overdue'"
    )


def downgrade() -> None:
    for col in reversed(_DROP_PATCH_COLUMNS):
        if col == "patch_reminders":
            from sqlalchemy.dialects import postgresql

            op.add_column(
                "hardware_requisitions",
                sa.Column(
                    "patch_reminders",
                    postgresql.JSONB(),
                    nullable=True,
                    comment="补办催办已发标签（t12/t2，幂等锚）",
                ),
                schema=SCHEMA,
            )
        else:
            op.add_column(
                "hardware_requisitions",
                sa.Column(
                    col,
                    sa.DateTime(timezone=True),
                    nullable=True,
                ),
                schema=SCHEMA,
            )
    op.drop_constraint(
        "ck_hardware_requisitions_status",
        "hardware_requisitions",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_hardware_requisitions_status",
        "hardware_requisitions",
        "status IN ('draft', 'pending', 'approved', 'issued', 'rejected',"
        " 'cancelled', 'overdue_unpatched')",
        schema=SCHEMA,
    )
    op.drop_column("hardware_requisitions", "urgent_reason", schema=SCHEMA)
