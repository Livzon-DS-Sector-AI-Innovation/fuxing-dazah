"""superagent 底座迁移 A —— 事件层 4 表 + cron_tick 自测源种子

Super-agent 平台底座一期（docs/DESIGN-SuperAgent底座-一期平台基座设计-20261102.md §5）：
- 新建 schema superagent（平台级，与 safety/audit/identity 惯例对齐）
- agent_sources / agent_source_cursors / agent_triggers / agent_threads
- 播种一律 ON CONFLICT DO NOTHING（幂等迁移教训）

Revision ID: f9a1c3e5d7b2
Revises: e8a4c2f0d9b3
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "f9a1c3e5d7b2"
down_revision: str | None = "e8a4c2f0d9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    op.create_table(
        "agent_sources",
        _uuid_pk(),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("config", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_agent_sources_name"),
        schema=_SCHEMA,
        comment="Source 注册实例（kind=插件稳定标识）",
    )

    op.create_table(
        "agent_source_cursors",
        _uuid_pk(),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "name", name="uq_agent_source_cursors"),
        schema=_SCHEMA,
        comment="持久化读位（推进仅在所覆盖 Trigger 全部落库后）",
    )

    op.create_table(
        "agent_triggers",
        _uuid_pk(),
        sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("thread_key", sa.String(512), nullable=False),
        sa.Column("actor", pg.JSONB(), nullable=True),
        sa.Column("human", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("addressed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("disposition", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "external_id", name="uq_agent_triggers_external"),
        schema=_SCHEMA,
        comment="不可变事件（(source,external_id) 唯一=DB 级幂等）",
    )
    op.create_index("ix_agent_triggers_thread", "agent_triggers", ["thread_key"], schema=_SCHEMA)
    op.create_index("ix_agent_triggers_received_at", "agent_triggers", ["received_at"], schema=_SCHEMA)

    op.create_table(
        "agent_threads",
        _uuid_pk(),
        sa.Column("thread_key", sa.String(512), nullable=False),
        sa.Column("label", sa.String(256), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("meta", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("thread_key", name="uq_agent_threads_key"),
        schema=_SCHEMA,
        comment="同话题事件时间序集合",
    )

    # 种子：cron_tick 自测源（默认停用；冒烟/验收时手动启用）
    op.execute(
        f"""
        INSERT INTO {_SCHEMA}.agent_sources (kind, name, config, enabled)
        VALUES (
            'cron_tick', 'superagent.selftest',
            '{{"job": "selftest", "schedule": {{"strategy": "interval", "interval_seconds": 3600}}}}'::jsonb,
            false
        )
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("agent_threads", schema=_SCHEMA)
    op.drop_table("agent_triggers", schema=_SCHEMA)
    op.drop_table("agent_source_cursors", schema=_SCHEMA)
    op.drop_table("agent_sources", schema=_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA}")
