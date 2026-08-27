"""add hr job_requirements duties column

胜任度分析报告「岗位要求回顾」需要岗位职责+任职要求两部分，
JD 表新增 duties（岗位职责描述）列。

Revision ID: 957424208cea
Revises: 21c784404a3e
Create Date: 2026-08-27 11:46:39.650820
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '957424208cea'
down_revision: str | None = '21c784404a3e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'job_requirements',
        sa.Column('duties', sa.Text(), nullable=True,
                  comment='岗位职责描述（胜任度报告「岗位要求回顾」用）'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('job_requirements', 'duties', schema='hr')
