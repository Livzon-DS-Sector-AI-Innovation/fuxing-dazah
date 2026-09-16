"""warehouse agent drafts add source

草稿来源渠道列（feishu/web）：分期B 快速登记页经 Web 通道建稿，
与飞书入口共用确认/提交流程，来源可追溯。

Revision ID: g8b2c6d4e1f3
Revises: f7a3b8c2d9e4
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g8b2c6d4e1f3'
down_revision: str | None = 'f7a3b8c2d9e4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'warehouse_agent_drafts',
        sa.Column('source', sa.String(length=16), server_default='feishu', nullable=False,
                  comment='来源渠道: feishu/web'),
        schema='warehouse',
    )


def downgrade() -> None:
    op.drop_column('warehouse_agent_drafts', 'source', schema='warehouse')
