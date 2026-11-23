"""五金库领用申请 —— 指定审批人（发起人自选节点）

申领人选择审批人（主管及以上）后再发起飞书审批：单头落 approver_user_id
（feishu user_id，创建实例时传 node_approver_user_id_list）+ approver_name
（展示）。manual 通道不消费该字段。

Revision ID: n9c2e4f6a8b1
Revises: i4d6f8a0c2e5
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n9c2e4f6a8b1"
down_revision: str | None = "i4d6f8a0c2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.add_column(
        "hardware_requisitions",
        sa.Column(
            "approver_user_id",
            sa.String(100),
            nullable=True,
            comment="指定审批人飞书 user_id（发起人自选节点，创建实例时传）",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "hardware_requisitions",
        sa.Column(
            "approver_name",
            sa.String(100),
            nullable=True,
            comment="指定审批人姓名（展示用）",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("hardware_requisitions", "approver_name", schema=SCHEMA)
    op.drop_column("hardware_requisitions", "approver_user_id", schema=SCHEMA)
