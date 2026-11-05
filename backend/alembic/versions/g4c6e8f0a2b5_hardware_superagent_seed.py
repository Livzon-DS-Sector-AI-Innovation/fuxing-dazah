"""五金库二期 M6 —— superagent 事件源播种 + 速递场景种子

- superagent.agent_sources 播种 warehouse.hardware_alert_scan
  （kind=hardware_alert_scan，enabled=false 默认——R1 先例： SUPERAGENT_ENABLED
  总开关 + per-source enabled 双闸，启用走 DB/运维动作）
- ai_scenario_configs 播种 hardware_digest_summary（速递 AI 总结场景行）

Policy 组合播种不走迁移：safety 桥 ensure_guardian_r2_policy 是
R1+R2+HW 三组合唯一会合点（启动播种，幂等）。

Revision ID: g4c6e8f0a2b5
Revises: f2a8c4e6d9b3
Create Date: 2026-11-05
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.modules.warehouse.ai_config import scenario_registry

revision: str = "g4c6e8f0a2b5"
down_revision: str | None = "f2a8c4e6d9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_NAME = "warehouse.hardware_alert_scan"
SCENARIO = "hardware_digest_summary"

_SOURCE_CONFIG = {
    "schedule": {"strategy": "interval", "interval_seconds": 3600,
                 "timezone": "Asia/Shanghai"},
    "evaluate": True,
    "draft_backlog_threshold": 5,
    "max_catchup_seconds": 86400,
}


def upgrade() -> None:
    import json

    config = json.dumps(_SOURCE_CONFIG, ensure_ascii=False).replace("'", "''")
    op.execute(
        f"""
        INSERT INTO superagent.agent_sources (kind, name, config, enabled)
        VALUES ('hardware_alert_scan', '{SOURCE_NAME}', '{config}'::jsonb, false)
        ON CONFLICT (name) DO NOTHING
        """
    )

    now = datetime.now(UTC)
    scenario_rows = sa.table(
        "ai_scenario_configs",
        sa.column("id", sa.Uuid()), sa.column("scenario", sa.String(64)),
        sa.column("enabled", sa.Boolean()), sa.column("model_profile", sa.String(32)),
        sa.column("is_deleted", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema="warehouse",
    )
    op.execute(postgresql.insert(scenario_rows).values([
        {"id": uuid4(), "scenario": info.scenario, "enabled": True,
         "model_profile": None, "is_deleted": False, "created_at": now, "updated_at": now}
        for info in scenario_registry.iter_scenarios()
        if info.scenario == SCENARIO
    ]).on_conflict_do_nothing())


def downgrade() -> None:
    op.execute(f"DELETE FROM superagent.agent_sources WHERE name = '{SOURCE_NAME}'")
    op.execute(f"DELETE FROM warehouse.ai_scenario_configs WHERE scenario = '{SCENARIO}'")
