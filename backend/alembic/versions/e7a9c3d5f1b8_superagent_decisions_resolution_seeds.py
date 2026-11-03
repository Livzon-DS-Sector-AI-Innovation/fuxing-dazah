"""superagent 迁移 E —— decisions 处置三列 + 冒烟③/需要人格种子

- agent_decisions 增 resolution/resolved_by/resolved_at（observe 回放人工处置）
- 种子① safety.fire_alarm：消防报警 bitable_poll 源（evaluate=true，默认停用）
- 种子② superagent.needs_human：每日 08:00 cron_tick 源（effect_kind=needs_human_cell，
  默认停用——「需要人」格构建走底座自身事件链）
ON CONFLICT DO NOTHING。

Revision ID: e7a9c3d5f1b8
Revises: d6f8b2c4e7a9
Create Date: 2026-11-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a9c3d5f1b8"
down_revision: str | None = "d6f8b2c4e7a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"

_FIRE_CONFIG = {
    "fetcher": "fire_alarm_ledger",
    "thread_prefix": "fire_alarm",
    "relevant_fields": ["报警性质", "原因分类", "处理情况", "报警类型", "部门"],
    "evaluate": True,
}

_NEEDS_HUMAN_CONFIG = {
    "job": "needs_human",
    "schedule": {"strategy": "fixed_time", "time_of_day": "08:00"},
    "effect_kind": "needs_human_cell",
}


def upgrade() -> None:
    op.add_column(
        "agent_decisions",
        sa.Column("resolution", sa.String(16), nullable=True,
                  comment="处置：promoted/dismissed（人工）"),
        schema=_SCHEMA,
    )
    op.add_column(
        "agent_decisions",
        sa.Column("resolved_by", sa.String(128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "agent_decisions",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )

    fire_cfg = json.dumps(_FIRE_CONFIG, ensure_ascii=False).replace("'", "''")
    needs_cfg = json.dumps(_NEEDS_HUMAN_CONFIG, ensure_ascii=False).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO {_SCHEMA}.agent_sources (kind, name, config, enabled)
        VALUES ('bitable_poll', 'safety.fire_alarm', '{fire_cfg}'::jsonb, false)
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO {_SCHEMA}.agent_sources (kind, name, config, enabled)
        VALUES ('cron_tick', 'superagent.needs_human', '{needs_cfg}'::jsonb, false)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM superagent.agent_sources WHERE name IN ('safety.fire_alarm', 'superagent.needs_human')")
    op.drop_column("agent_decisions", "resolved_at", schema=_SCHEMA)
    op.drop_column("agent_decisions", "resolved_by", schema=_SCHEMA)
    op.drop_column("agent_decisions", "resolution", schema=_SCHEMA)
