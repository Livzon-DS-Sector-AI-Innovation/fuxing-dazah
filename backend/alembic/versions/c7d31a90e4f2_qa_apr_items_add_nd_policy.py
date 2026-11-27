"""qa apr 列定义增加未检出统计口径 nd_policy

Revision ID: c7d31a90e4f2
Revises: ba295b00e29e
Create Date: 2026-11-09 10:12:00.000000

数值列允许填文字结果（如 未检出）后，统计口径列级可配：
zero 按 0 计入统计（默认，存量列沿用）/ exclude 不进统计。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d31a90e4f2'
down_revision: str | None = 'ba295b00e29e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'apr_items',
        sa.Column(
            'nd_policy',
            sa.String(length=8),
            server_default='zero',
            nullable=False,
            comment='数值列未检出统计口径：zero 按0计入 / exclude 不计入',
        ),
        schema='qa',
    )
    op.create_check_constraint(
        'ck_qa_apr_items_nd_policy',
        'apr_items',
        "nd_policy IN ('zero', 'exclude')",
        schema='qa',
    )


def downgrade() -> None:
    op.drop_constraint('ck_qa_apr_items_nd_policy', 'apr_items', schema='qa')
    op.drop_column('apr_items', 'nd_policy', schema='qa')
