"""qa apr 列定义增加快捷文字结果 quick_values

Revision ID: 43ce8e669702
Revises: fd8da0093c43
Create Date: 2026-11-09 15:47:27.315657

数值列允许录入的文字结果改为列级白名单：录入页按该列渲染快捷按钮，
保存时校验 value_text 必须命中白名单；存量列默认沿用 未检出/<1。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '43ce8e669702'
down_revision: str | None = 'fd8da0093c43'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'apr_items',
        sa.Column(
            'quick_values',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text('\'["未检出","<1"]\'::jsonb'),
            nullable=False,
            comment='数值列允许录入的文字结果（录入页快捷按钮）；非白名单文字拒绝保存',
        ),
        schema='qa',
    )


def downgrade() -> None:
    op.drop_column('apr_items', 'quick_values', schema='qa')
