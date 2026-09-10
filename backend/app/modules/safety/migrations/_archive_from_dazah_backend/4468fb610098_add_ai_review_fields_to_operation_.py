"""add ai_review fields to operation_regulations

Revision ID: 4468fb610098
Revises: b8d2e4f6a8c0
Create Date: 2026-08-12 09:56:41.714821
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4468fb610098'
down_revision: Union[str, None] = 'b8d2e4f6a8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 safety.operation_regulations 的 AI 审核两列。

    注意：autogenerate 混入了其他模块/历史漂移，已手动清理，仅保留本需求 DDL。
    """
    op.add_column(
        'operation_regulations',
        sa.Column('ai_review_status', sa.String(length=20), server_default='pending', nullable=False,
                  comment='AI 审核状态: pending/reviewing/completed/failed'),
        schema='safety',
    )
    op.add_column(
        'operation_regulations',
        sa.Column('ai_review_note', sa.JSON(), nullable=True,
                  comment='AI 审核说明 {summary, dimensions, chapter_fixes, reviewed_at}'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('operation_regulations', 'ai_review_note', schema='safety')
    op.drop_column('operation_regulations', 'ai_review_status', schema='safety')
