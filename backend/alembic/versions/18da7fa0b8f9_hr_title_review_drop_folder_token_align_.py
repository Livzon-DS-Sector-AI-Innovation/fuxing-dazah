"""hr_title_review_drop_folder_token_align_pass_ratio_default

Revision ID: 18da7fa0b8f9
Revises: 39c34ac3a668
Create Date: 2026-08-26 08:59:20.246382
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '18da7fa0b8f9'
down_revision: str | None = '39c34ac3a668'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 清理死状态：feishu_folder_token 从未被读写（v2 自动建表时代的备用列）
    op.drop_column(
        "title_review_activities", "feishu_folder_token", schema="hr"
    )
    # 服务器默认值对齐 Python 默认 2/3（双精度最接近值），避免恰好 2/3 边界判失败
    op.alter_column(
        "title_review_activities",
        "pass_ratio",
        existing_type=sa.Float(),
        server_default="0.6666666666666667",
        existing_nullable=False,
        schema="hr",
    )


def downgrade() -> None:
    op.alter_column(
        "title_review_activities",
        "pass_ratio",
        existing_type=sa.Float(),
        server_default="0.6667",
        existing_nullable=False,
        schema="hr",
    )
    op.add_column(
        "title_review_activities",
        sa.Column(
            "feishu_folder_token",
            sa.String(length=64),
            nullable=True,
            comment="备用：存放多维表格的文件夹 token",
        ),
        schema="hr",
    )
