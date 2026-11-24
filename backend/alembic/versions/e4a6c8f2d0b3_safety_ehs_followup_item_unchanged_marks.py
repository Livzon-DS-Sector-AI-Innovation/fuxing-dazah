"""safety ehs_change_followup_items 加列 —— 单项「进展不变」勾选标记

2026-11-24 实机测试反馈改版（用户拍板）：周五卡改为**每个变更一个填写框**，
可填新进展或勾选「进展不变，无需更新」，一次提交——「进展不变」从卡级
按钮下沉为单项级标记，周一②类的判定源随之改读 item.marked_unchanged。

Revision ID: e4a6c8f2d0b3
Revises: d7f2b6e4a9c1
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4a6c8f2d0b3"
down_revision: str | None = "d7f2b6e4a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ehs_change_followup_items"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "marked_unchanged", sa.Boolean(), server_default="false",
            nullable=False,
            comment="安全员在该项上勾选了「进展不变，无需更新」",
        ),
        schema="safety",
    )
    op.add_column(
        _TABLE,
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True,
                  comment="勾选时间"),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "marked_at", schema="safety")
    op.drop_column(_TABLE, "marked_unchanged", schema="safety")
