"""warehouse agent drafts chat_id

Revision ID: de658374847a
Revises: 7bf849ceb7e2
Create Date: 2026-09-09 10:33:04.406002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'de658374847a'
down_revision: Union[str, None] = '7bf849ceb7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "warehouse_agent_drafts",
        sa.Column("chat_id", sa.String(length=60), nullable=True, comment="发起会话 chat_id（回执按原渠道回复）"),
        schema="warehouse",
    )


def downgrade() -> None:
    op.drop_column("warehouse_agent_drafts", "chat_id", schema="warehouse")
