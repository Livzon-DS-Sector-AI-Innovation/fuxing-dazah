"""safety scheduler_task_configs add dom column

消防报警周报改月报（2026-09-22，每月 1 日 08:30）：调度器新增 dom
（每月几号）过滤；scheduler_task_configs 补 dom 列，使 DB 覆写与
hour/minute/dow 对齐（NULL = 使用代码默认值）。

Revision ID: b7e4f1a9c3d2
Revises: c5a9d3e7f1b2
Create Date: 2026-09-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e4f1a9c3d2'
down_revision: str | None = 'c5a9d3e7f1b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'scheduler_task_configs',
        sa.Column(
            'dom',
            sa.Integer(),
            nullable=True,
            comment='每月几号 1-31，NULL=不限（月报类任务）',
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('scheduler_task_configs', 'dom', schema='safety')
