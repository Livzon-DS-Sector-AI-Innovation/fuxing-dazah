"""hr title review widen approval instance code

Revision ID: 9add14ff9b5e
Revises: d995896d9437
Create Date: 2026-08-25 11:14:12.440224
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9add14ff9b5e'
down_revision: str | None = 'd995896d9437'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 仅职称评审模块：审批实例编号列加宽（重复提交时逗号累积多个编号）
    op.alter_column(
        'title_review_applications',
        'approval_instance_code',
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=255),
        comment='飞书审批实例编码，重复提交时逗号累积（审批先行模式，防重复同步）',
        existing_comment='飞书审批实例编码（审批先行模式，防重复同步）',
        existing_nullable=True,
        schema='hr',
    )


def downgrade() -> None:
    op.alter_column(
        'title_review_applications',
        'approval_instance_code',
        existing_type=sa.String(length=255),
        type_=sa.VARCHAR(length=64),
        comment='飞书审批实例编码（审批先行模式，防重复同步）',
        existing_comment='飞书审批实例编码，重复提交时逗号累积（审批先行模式，防重复同步）',
        existing_nullable=True,
        schema='hr',
    )
