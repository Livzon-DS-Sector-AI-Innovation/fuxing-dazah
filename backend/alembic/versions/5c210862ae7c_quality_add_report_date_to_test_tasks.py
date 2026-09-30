"""quality add report_date to test tasks

Revision ID: 5c210862ae7c
Revises: 27375e84e8c7
Create Date: 2026-09-10 14:33:21.175947
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5c210862ae7c'
down_revision: Union[str, None] = '27375e84e8c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'quality_test_tasks',
        sa.Column(
            'report_date',
            sa.String(length=32),
            nullable=True,
            comment='出报日期（YYYY-MM-DD，可后补；关联当日机器人任务推送）',
        ),
        schema='quality',
    )


def downgrade() -> None:
    op.drop_column('quality_test_tasks', 'report_date', schema='quality')
