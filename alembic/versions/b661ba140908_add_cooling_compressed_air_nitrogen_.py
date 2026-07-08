"""add cooling compressed_air nitrogen natural_gas energy types

Revision ID: b661ba140908
Revises: 53edf731cdb6
Create Date: 2026-06-26 10:37:25.625231
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b661ba140908'
down_revision: Union[str, None] = '53edf731cdb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_TYPES = "', '".join(["cooling", "compressed_air", "nitrogen", "natural_gas"])
_ALL_TYPES = "', '".join([
    "electricity", "water", "steam",
    "cooling", "compressed_air", "nitrogen", "natural_gas",
])
_OLD_TYPES = "', '".join(["electricity", "water", "steam"])


def upgrade() -> None:
    # 1. 更新 CHECK 约束：增加 4 种新类型
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT IF EXISTS ck_energy_device_config_energy_type"
    )
    op.create_check_constraint(
        "ck_energy_device_config_energy_type",
        "energy_device_configs",
        f"energy_type IN ('{_ALL_TYPES}')",
        schema="energy",
    )
    op.execute(
        "ALTER TABLE energy.energy_alert_rules "
        "DROP CONSTRAINT IF EXISTS ck_energy_alert_rule_energy_type"
    )
    op.create_check_constraint(
        "ck_energy_alert_rule_energy_type",
        "energy_alert_rules",
        f"energy_type IN ('{_ALL_TYPES}')",
        schema="energy",
    )

    # 2. 插入新增的 4 种能源类型 seed 数据
    op.execute(
        "INSERT INTO energy.energy_type_configs "
        "(id, type_code, display_name, unit, sort_order, is_enabled, is_deleted) VALUES "
        "('00000000-0000-0000-0000-000000000004', 'cooling',        '冷量数据',   'kW',  4, true, false),"
        "('00000000-0000-0000-0000-000000000005', 'compressed_air', '压缩空气数据', 'Nm³', 5, true, false),"
        "('00000000-0000-0000-0000-000000000006', 'nitrogen',       '氮气数据',   'Nm³', 6, true, false),"
        "('00000000-0000-0000-0000-000000000007', 'natural_gas',    '天然气数据',  'Nm³', 7, true, false) "
        "ON CONFLICT (type_code, is_deleted) DO UPDATE SET "
        "display_name = EXCLUDED.display_name, unit = EXCLUDED.unit, sort_order = EXCLUDED.sort_order"
    )


def downgrade() -> None:
    # 1. 删除新增的 4 种能源类型 seed 数据
    op.execute(
        "DELETE FROM energy.energy_type_configs "
        f"WHERE type_code IN ('{_NEW_TYPES}')"
    )

    # 2. 回退 CHECK 约束
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT IF EXISTS ck_energy_device_config_energy_type"
    )
    op.create_check_constraint(
        "ck_energy_device_config_energy_type",
        "energy_device_configs",
        f"energy_type IN ('{_OLD_TYPES}')",
        schema="energy",
    )
    op.execute(
        "ALTER TABLE energy.energy_alert_rules "
        "DROP CONSTRAINT IF EXISTS ck_energy_alert_rule_energy_type"
    )
    op.create_check_constraint(
        "ck_energy_alert_rule_energy_type",
        "energy_alert_rules",
        f"energy_type IN ('{_OLD_TYPES}')",
        schema="energy",
    )
