"""superagent 底座迁移 B —— 副作用层 3 表（effects/outbox/health）

- agent_effects：待处理 (kind, dedupe_key) 部分唯一（done/failed 不占键可再入队）
- agent_outbox：seq 自增保序 + next_due_at 队头节流 + 行内权威地址
- agent_health：一组件一行认领制
播种：无（健康条目由进程启动认领）

Revision ID: a2c4e6f8b1d3
Revises: f9a1c3e5d7b2
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "a2c4e6f8b1d3"
down_revision: str | None = "f9a1c3e5d7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.create_table(
        "agent_effects",
        _uuid_pk(),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("dedupe_key", sa.String(512), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=_SCHEMA,
        comment="外部副作用队列（先存后做；待处理 (kind,dedupe_key) 唯一）",
    )
    op.execute(
        f"CREATE UNIQUE INDEX uq_agent_effects_pending ON {_SCHEMA}.agent_effects "
        "(kind, dedupe_key) WHERE status = 'pending'"
    )
    op.create_index(
        "ix_agent_effects_due", "agent_effects", ["status", "next_due_at"], schema=_SCHEMA,
    )

    op.create_table(
        "agent_outbox",
        _uuid_pk(),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation", sa.String(512), nullable=False),
        sa.Column("channel", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("purpose", sa.String(64), nullable=False, server_default="message"),
        sa.Column("body", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dropped_reason", sa.String(256), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("seq", name="uq_agent_outbox_seq"),
        schema=_SCHEMA,
        comment="会话内保序消息（同 (task,conversation) 按 seq 严格顺序；行内地址权威）",
    )
    op.create_index(
        "ix_agent_outbox_conv", "agent_outbox", ["conversation", "status", "seq"],
        schema=_SCHEMA,
    )
    op.create_index("ix_agent_outbox_task", "agent_outbox", ["task_id"], schema=_SCHEMA)

    op.create_table(
        "agent_health",
        _uuid_pk(),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="paused"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("component", name="uq_agent_health_component"),
        schema=_SCHEMA,
        comment="组件健康（一组件一行认领制）",
    )


def downgrade() -> None:
    op.drop_table("agent_health", schema=_SCHEMA)
    op.drop_table("agent_outbox", schema=_SCHEMA)
    op.drop_table("agent_effects", schema=_SCHEMA)
