"""superagent 底座冒烟②种子 —— hazard 督办 bitable_poll 源实例（默认停用）

源实例 safety.hazard.supervision：fetcher=hazard_ledger（安全侧桥接注册），
相关字段指纹含 整改状态/隐患级别（人工）/检查日期/责任部门/检查类别——
督办等级列刻意不进指纹（自写回声抑制）；effect_kind=supervision_writeback。
ON CONFLICT DO NOTHING（幂等播种铁律）。

Revision ID: b4d6f8a2c5e7
Revises: a2c4e6f8b1d3
Create Date: 2026-11-02
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "b4d6f8a2c5e7"
down_revision: str | None = "a2c4e6f8b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_CONFIG = {
    "fetcher": "hazard_ledger",
    "thread_prefix": "hazard",
    "relevant_fields": [
        "整改状态", "隐患级别（人工）", "检查日期", "责任部门", "检查类别",
    ],
    "effect_kind": "supervision_writeback",
}


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO superagent.agent_sources (kind, name, config, enabled)
        VALUES (
            'bitable_poll', 'safety.hazard.supervision',
            '{config}'::jsonb,
            false
        )
        ON CONFLICT (name) DO NOTHING
        """.format(
            config=json.dumps(_SOURCE_CONFIG, ensure_ascii=False).replace("'", "''")
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM superagent.agent_sources WHERE name = 'safety.hazard.supervision'")
