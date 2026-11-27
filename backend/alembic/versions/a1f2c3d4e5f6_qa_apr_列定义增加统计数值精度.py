"""qa apr 列定义增加统计数值精度 stat_precision

Revision ID: a1f2c3d4e5f6
Revises: 43ce8e669702
Create Date: 2026-11-10 16:05:00.000000

对齐年度回顾工具 qa_year_review 的「统计数值精度」列级配置：
控制汇总表尾/Excel 导出/Word 报告里统计值的小数位；空 = 默认 2 位。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5f6'
down_revision: str | None = '43ce8e669702'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'apr_items',
        sa.Column(
            'stat_precision',
            sa.SmallInteger(),
            nullable=True,
            comment='统计数值精度（小数位）；空=2，导出/报告格式化用',
        ),
        schema='qa',
    )
    op.create_check_constraint(
        'ck_qa_apr_items_stat_precision',
        'apr_items',
        'stat_precision IS NULL OR stat_precision BETWEEN 0 AND 6',
        schema='qa',
    )


def downgrade() -> None:
    op.drop_constraint(
        'ck_qa_apr_items_stat_precision', 'apr_items', schema='qa'
    )
    op.drop_column('apr_items', 'stat_precision', schema='qa')
