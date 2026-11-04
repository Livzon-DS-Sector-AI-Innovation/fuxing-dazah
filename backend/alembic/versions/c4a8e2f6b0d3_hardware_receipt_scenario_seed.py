"""hardware_receipt_recognition scenario seed

五金库送货单识别熔断场景行（M2）：scenario_registry 新增
hardware_receipt_recognition——不播种则 live「播种行数=注册表数」断言
不一致（test_live_system_config），沿 a9d4e7f2c6b8 先例。

Revision ID: c4a8e2f6b0d3
Revises: b2f6d8e0a4c1
Create Date: 2026-11-04
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.modules.warehouse.ai_config import scenario_registry

revision: str = "c4a8e2f6b0d3"
down_revision: str | None = "b2f6d8e0a4c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCENARIO = "hardware_receipt_recognition"


def upgrade() -> None:
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
    op.execute(
        f"DELETE FROM warehouse.ai_scenario_configs WHERE scenario = '{SCENARIO}'"
    )
