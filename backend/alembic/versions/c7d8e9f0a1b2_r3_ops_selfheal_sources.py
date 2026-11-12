"""R3 运维自愈 —— ops_scan 扫描源 + rag 直投载体行播种（默认停用）

- superagent.agent_sources 播种两行：
  · safety.ops.selfheal（kind=ops_scan，interval 300s 兜底 schedule——生效值
    以 SAFETY_R3_SCAN_INTERVAL_SECONDS 每轮热读为准；evaluate=true）
  · safety.ops.rag_inject（kind=rag_direct，enabled 恒 false 仅归属载体，
    直投走 ingest_draft 不经轮询；evaluate=true）
- enabled=false：三层开关链（SUPERAGENT_ENABLED → SAFETY_R3_OPS_ENABLED →
  source.enabled）默认全关，播种不等于启用
播种一律 ON CONFLICT DO NOTHING（幂等播种铁律，仿 a1b3c5d7e9f1）。

Revision ID: c7d8e9f0a1b2
Revises: d1e2f4a6b8c5
Create Date: 2026-11-12
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "d1e2f4a6b8c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCAN_SOURCE_CONFIG = {
    "schedule": {
        "strategy": "interval",
        "interval_seconds": 300,
        "timezone": "Asia/Shanghai",
    },
    "evaluate": True,
}

_RAG_SOURCE_CONFIG = {
    "evaluate": True,
}


def _seed(name: str, kind: str, config: dict, *, enabled: bool) -> None:
    """播种一行源（注意列序：kind 在前 name 在后，对齐 a1b3c5d7e9f1 内联样板）。"""
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
    # 列序坑（审查 BLOCK）：INSERT 列序 kind,name——实参按 (name, kind) 关键字传递
    _seed(name="safety.ops.selfheal", kind="ops_scan", config=_SCAN_SOURCE_CONFIG, enabled=False)
    _seed(name="safety.ops.rag_inject", kind="rag_direct", config=_RAG_SOURCE_CONFIG, enabled=False)


def downgrade() -> None:
    op.execute(
        "DELETE FROM superagent.agent_sources "
        "WHERE name IN ('safety.ops.selfheal', 'safety.ops.rag_inject')"
    )
