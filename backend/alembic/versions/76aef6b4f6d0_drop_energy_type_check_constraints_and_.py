"""drop energy_type CHECK constraints and seed default types

Revision ID: 76aef6b4f6d0
Revises: c9fffc9a39a5
Create Date: 2026-07-27 09:20:05.974010
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '76aef6b4f6d0'
down_revision: Union[str, None] = 'c9fffc9a39a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 默认 7 种能源类型种子数据
SEED_TYPES = [
    ("electricity",    "电耗数据",   "kWh",  "#0075de", 1),
    ("water",          "水耗数据",   "m³", "#1aae39", 2),
    ("steam",          "蒸汽数据",   "t",    "#dd5b00", 3),
    ("cooling",        "冷量数据",   "kW",   "#722ed1", 4),
    ("compressed_air", "压缩空气数据", "Nm³", "#2f54eb", 5),
    ("nitrogen",       "氮气数据",   "Nm³", "#fa541c", 6),
    ("natural_gas",    "天然气数据",  "Nm³", "#faad14", 7),
]


def upgrade() -> None:
    # 1. 删除 CHECK 约束，不再限制 energy_type 的取值
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT IF EXISTS ck_energy_device_config_energy_type"
    )
    op.execute(
        "ALTER TABLE energy.energy_alert_rules "
        "DROP CONSTRAINT IF EXISTS ck_energy_alert_rule_energy_type"
    )

    # 2. 幂等插入种子能源类型（ON CONFLICT DO UPDATE）
    for type_code, display_name, unit, color, sort_order in SEED_TYPES:
        op.execute(
            f"INSERT INTO energy.energy_type_configs "
            f"(id, type_code, display_name, unit, color, sort_order, is_enabled, is_deleted, created_at, updated_at) "
            f"VALUES (gen_random_uuid(), '{type_code}', '{display_name}', '{unit}', '{color}', {sort_order}, true, false, now(), now()) "
            f"ON CONFLICT (type_code, is_deleted) DO UPDATE SET "
            f"display_name = EXCLUDED.display_name, "
            f"unit = EXCLUDED.unit, "
            f"color = EXCLUDED.color, "
            f"sort_order = EXCLUDED.sort_order"
        )


def downgrade() -> None:
    # 回退：恢复 CHECK 约束（限制为 7 种已知类型）
    _ALL_TYPES = "', '".join(t[0] for t in SEED_TYPES)
    op.create_check_constraint(
        "ck_energy_device_config_energy_type",
        "energy_device_configs",
        f"energy_type IN ('{_ALL_TYPES}')",
        schema="energy",
    )
    op.create_check_constraint(
        "ck_energy_alert_rule_energy_type",
        "energy_alert_rules",
        f"energy_type IN ('{_ALL_TYPES}')",
        schema="energy",
    )
