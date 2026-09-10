"""add card_message_id to agent_pending_actions

Revision ID: 8f2e8deae727
Revises: m1n2o3p4q5r6
Create Date: 2026-07-21 08:34:42.530115
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8f2e8deae727'
down_revision: str | None = 'm1n2o3p4q5r6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'agent_pending_actions',
        sa.Column(
            'card_message_id',
            sa.String(length=128),
            nullable=True,
            comment='飞书确认卡片的 message_id（用于点击按钮后更新卡片状态）',
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('agent_pending_actions', 'card_message_id', schema='safety')
