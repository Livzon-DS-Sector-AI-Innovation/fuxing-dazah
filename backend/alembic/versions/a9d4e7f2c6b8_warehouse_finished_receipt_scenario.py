"""warehouse finished_receipt recognition scenario seed

成品入库识别熔断场景行（V3.0 §4.6）：scenario_registry 新增
finished_receipt_recognition——不播种则 live「播种行数=注册表数」断言
不一致（test_live_system_config），沿 A 期 runtime 补种先例。

Revision ID: a9d4e7f2c6b8
Revises: f8a3c1d5b7e9
Create Date: 2026-09-21
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op
from app.modules.warehouse.ai_config import scenario_registry

# revision identifiers, used by Alembic.
revision: str = 'a9d4e7f2c6b8'
down_revision: str | None = 'f8a3c1d5b7e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE_SCENARIO = "finished_receipt_recognition"


def upgrade() -> None:
    now = datetime.now(UTC)
    scenario_rows = sa.table(
        'ai_scenario_configs',
        sa.column('id', sa.Uuid()), sa.column('scenario', sa.String(64)),
        sa.column('enabled', sa.Boolean()), sa.column('model_profile', sa.String(32)),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(scenario_rows, [
        {"id": uuid4(), "scenario": info.scenario, "enabled": True,
         "model_profile": None, "is_deleted": False, "created_at": now, "updated_at": now}
        for info in scenario_registry.iter_scenarios()
        if info.scenario == PHASE_SCENARIO
    ])


def downgrade() -> None:
    op.execute(
        "DELETE FROM warehouse.ai_scenario_configs WHERE scenario = 'finished_receipt_recognition'"
    )
