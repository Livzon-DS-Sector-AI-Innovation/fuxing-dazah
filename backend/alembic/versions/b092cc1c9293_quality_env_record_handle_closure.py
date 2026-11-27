"""quality env record handle closure

Revision ID: b092cc1c9293
Revises: 00fdde9f7d30
Create Date: 2026-10-23 15:01:37.152817
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b092cc1c9293'
down_revision: str | None = '00fdde9f7d30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 超行动限记录闭环：未处理/已处理 + 处理人/日期/说明
    op.add_column("quality_env_records", sa.Column("handle_status", sa.String(length=16), server_default="open", nullable=False, comment="open 未处理 / handled 已处理（仅超行动限记录需要闭环）"), schema="quality")
    op.add_column("quality_env_records", sa.Column("handled_at", sa.String(length=32), nullable=True, comment="处理日期 YYYY-MM-DD"), schema="quality")
    op.add_column("quality_env_records", sa.Column("handled_by", sa.Uuid(), nullable=True, comment="处理人，逻辑引用 identity.users.id"), schema="quality")
    op.add_column("quality_env_records", sa.Column("handled_remark", sa.String(length=200), nullable=True, comment="处理说明"), schema="quality")


def downgrade() -> None:
    op.drop_column("quality_env_records", "handled_remark", schema="quality")
    op.drop_column("quality_env_records", "handled_by", schema="quality")
    op.drop_column("quality_env_records", "handled_at", schema="quality")
    op.drop_column("quality_env_records", "handle_status", schema="quality")
