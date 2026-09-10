"""Add business_agent tables (sessions, messages, pending_actions, user_roles).

Revision ID: a1b2c3d4e5f7
Revises: 425cd778d104
Create Date: 2026-07-10

四张表均落在 ``safety`` schema，支持软删除（``is_deleted``），无数据库级 FK 约束。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import func

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "425cd778d104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
        sa.Column("channel", sa.String(32), nullable=False, server_default="web"),
        sa.Column("chat_id", sa.String(128), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("message_history", postgresql.JSONB, nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema="safety",
    )
    op.create_index(
        "ix_agent_sessions_channel_chat_id", "agent_sessions",
        ["channel", "chat_id"], schema="safety",
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("agent_answer", sa.Text(), nullable=True),
        sa.Column("pending_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema="safety",
    )
    op.create_index(
        "ix_agent_messages_session_id", "agent_messages",
        ["session_id"], schema="safety",
    )

    op.create_table(
        "agent_pending_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("arguments", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("message_history_snapshot", postgresql.JSONB, nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema="safety",
    )
    op.create_index(
        "ix_agent_pending_actions_session_id", "agent_pending_actions",
        ["session_id"], schema="safety",
    )

    op.create_table(
        "agent_user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
        sa.Column("feishu_user_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=func.now()),
        schema="safety",
    )
    op.create_index(
        "ix_agent_user_roles_feishu_user_id", "agent_user_roles",
        ["feishu_user_id"], unique=True, schema="safety",
    )


def downgrade() -> None:
    op.drop_table("agent_user_roles", schema="safety")
    op.drop_table("agent_pending_actions", schema="safety")
    op.drop_table("agent_messages", schema="safety")
    op.drop_table("agent_sessions", schema="safety")
