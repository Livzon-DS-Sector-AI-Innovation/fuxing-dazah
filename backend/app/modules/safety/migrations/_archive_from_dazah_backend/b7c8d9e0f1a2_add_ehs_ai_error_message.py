"""add ai_error_message to ehs_changes

记录 AI 审核失败原因（failed 时写入，completed 时清空）。

Revision ID: b7c8d9e0f1a2
Revises: e5f6a7b8c9d0
Create Date: 2026-08-03
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'ehs_changes',
        sa.Column('ai_error_message', sa.Text(), nullable=True,
                  comment='AI审核失败信息（failed 时记录，completed 时清空）'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('ehs_changes', 'ai_error_message', schema='safety')
