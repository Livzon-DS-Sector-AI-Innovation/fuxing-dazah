"""五金库三期 —— 播种三个运行参数键（ERP 列映射 / M9 auto-direct 开关与阈值）

新运行参数注册（runtime_registry 三期 +3 键）后，live 库 runtime_configs
需有对应行（test_live_system_config.test_seeded_row_counts_match_registries
断言行数=注册表长度）。

播种值=注册表默认（开关 0 / 阈值 0.9 / 列映射空串）——行为与未播种完全
一致；行存在后 DB 通道生效（source=db），env 仅作 pre-migration 兜底
（store._resolve：DB 活行非 NULL 即优先，coerce 失败回落默认不看 env——
故 int/float 键播种 "" 会吞掉 env 通道，必须落真值）。

Revision ID: d1e2f4a6b8c5
Revises: c9d5e7f3a8b6
Create Date: 2026-11-05
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1e2f4a6b8c5"
down_revision = "c9d5e7f3a8b6"
branch_labels = None
depends_on = None

#: key → 播种值（=runtime_registry 默认；str 映射键空串=内置默认映射）
SEED_VALUES = {
    "hardware_erp_column_mapping": "",
    "hardware_ocr_auto_direct_enabled": 0,
    "hardware_ocr_auto_direct_min_confidence": 0.9,
}


def upgrade() -> None:
    op.execute(
        postgresql.insert(
            sa.table(
                "runtime_configs",
                sa.column("id", postgresql.UUID()),
                sa.column("key", sa.String(64)),
                sa.column("value", postgresql.JSONB()),
                sa.column("is_deleted", sa.Boolean()),
                sa.column("created_at", sa.DateTime()),
                sa.column("updated_at", sa.DateTime()),
                schema="warehouse",
            )
        ).values(
            [
                {
                    "id": uuid.uuid4(),
                    "key": key,
                    "value": value,
                    "is_deleted": False,
                    "created_at": sa.func.now(),
                    "updated_at": sa.func.now(),
                }
                for key, value in SEED_VALUES.items()
            ]
        ).on_conflict_do_nothing()
    )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in SEED_VALUES)
    op.execute(f"DELETE FROM warehouse.runtime_configs WHERE key IN ({keys})")
