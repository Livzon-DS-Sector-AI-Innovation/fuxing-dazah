"""R3 运维自愈二期 —— event 失败直投载体行播种（默认停用）

- superagent.agent_sources 播种一行：safety.ops.event_inject（kind=event_direct，
  enabled 恒 false 仅归属载体，直投走 ingest_draft 不经轮询；evaluate=true）
- enabled=false：三层开关链默认全关，播种不等于启用
播种一律 ON CONFLICT DO NOTHING（幂等播种铁律，仿 a1b3c5d7e9f1 / c7d8e9f0a1b2）。

Revision ID: a5c7e9b1d3f2
Revises: c7d8e9f0a1b2
Create Date: 2026-11-12
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "a5c7e9b1d3f2"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_SOURCE_CONFIG = {
    "evaluate": True,
}


def _seed(*, name: str, kind: str, config: dict, enabled: bool) -> None:
    """播种一行源（列序 kind,name——实参一律关键字传递，防一期 BLOCK 雷复发）。"""
    op.execute(
        """
        INSERT INTO superagent.agent_sources (kind, name, config, enabled)
        VALUES ('{kind}', '{name}', '{config}'::jsonb, {enabled})
        ON CONFLICT (name) DO NOTHING
        """.format(
            kind=kind,
            name=name,
            config=json.dumps(config, ensure_ascii=False).replace("'", "''"),
            enabled="true" if enabled else "false",
        )
    )


def upgrade() -> None:
    _seed(
        name="safety.ops.event_inject", kind="event_direct",
        config=_EVENT_SOURCE_CONFIG, enabled=False,
    )
    # 一期 BLOCK 雷防复发：种子后 kind/name 归位断言（错位即迁移失败）
    row = op.execute(
        "SELECT kind FROM superagent.agent_sources WHERE name = 'safety.ops.event_inject'"
    ).scalar_one_or_none()
    if row != "event_direct":
        raise RuntimeError(
            f"event_inject 种子归位断言失败: name='safety.ops.event_inject' 的 kind={row!r} (期望 'event_direct')"
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM superagent.agent_sources WHERE name = 'safety.ops.event_inject'"
    )
