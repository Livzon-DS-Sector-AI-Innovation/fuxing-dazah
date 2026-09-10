"""add agent_memories table

Revision ID: m1n2o3p4q5r6
Revises: dbd4fbaf6f41
Create Date: 2026-07-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m1n2o3p4q5r6"
down_revision: str | None = "dbd4fbaf6f41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(128), nullable=False,
                  comment="identity.users.feishu_user_id"),
        sa.Column("memory_type", sa.String(32), nullable=False,
                  comment="记忆类型：fact / preference / episode / workflow"),
        sa.Column("content", sa.Text(), nullable=False,
                  comment="人类可读的记忆内容"),
        sa.Column("embedding", sa.Text(), nullable=True,
                  comment="JSON-stringified 2048-dim 向量（供语义检索）"),
        sa.Column("importance", sa.Float(), nullable=False,
                  server_default="0.5", comment="重要性评分 (0-1)"),
        sa.Column("confidence", sa.Float(), nullable=False,
                  server_default="1.0", comment="置信度 (0-1)"),
        sa.Column("access_count", sa.Integer(), nullable=False,
                  server_default="0", comment="被检索次数"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True,
                  comment="最后检索时间"),
        sa.Column("source_session_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="来源会话（agent_sessions.id）"),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="来源消息（agent_messages.id）"),
        sa.Column("metadata_", postgresql.JSONB(), nullable=True,
                  server_default=sa.text("'{}'::jsonb"), comment="扩展元数据"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True,
                  comment="过期时间（NULL=永不过期）"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        schema="safety",
    )
    op.create_index(
        "ix_agent_memories_user_type",
        "agent_memories",
        ["user_id", "memory_type"],
        schema="safety",
    )
    op.create_index(
        "ix_agent_memories_user_importance",
        "agent_memories",
        ["user_id", "importance"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index("ix_agent_memories_user_importance", table_name="agent_memories", schema="safety")
    op.drop_index("ix_agent_memories_user_type", table_name="agent_memories", schema="safety")
    op.drop_table("agent_memories", schema="safety")
