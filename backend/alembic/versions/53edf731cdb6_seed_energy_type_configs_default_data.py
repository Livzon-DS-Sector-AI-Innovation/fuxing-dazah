"""seed_energy_type_configs_default_data

Revision ID: 53edf731cdb6
Revises: 7e70c41a9cdc
Create Date: 2026-06-25 18:16:08.447331
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53edf731cdb6'
down_revision: Union[str, None] = '7e70c41a9cdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 先删除旧 CHECK 约束（gas → steam 的 UPDATE 需要 steam 不在旧约束中）
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT IF EXISTS ck_energy_device_config_energy_type"
    )
    op.execute(
        "ALTER TABLE energy.energy_alert_rules "
        "DROP CONSTRAINT IF EXISTS ck_energy_alert_rule_energy_type"
    )

    # 2. 将旧数据 gas → steam
    op.execute(
        "UPDATE energy.energy_device_configs SET energy_type = 'steam' "
        "WHERE energy_type = 'gas'"
    )
    op.execute(
        "UPDATE energy.energy_alert_rules SET energy_type = 'steam' "
        "WHERE energy_type = 'gas'"
    )

    # 3. 添加新 CHECK 约束（electricity / water / steam）
    op.create_check_constraint(
        "ck_energy_device_config_energy_type",
        "energy_device_configs",
        "energy_type IN ('electricity', 'water', 'steam')",
        schema="energy",
    )
    op.create_check_constraint(
        "ck_energy_alert_rule_energy_type",
        "energy_alert_rules",
        "energy_type IN ('electricity', 'water', 'steam')",
        schema="energy",
    )

    # 4. 插入默认能源类型（来自 formulaId.csv + EMTRNUM.csv 的数据表名称）
    #    使用 ON CONFLICT DO NOTHING 保证幂等
    op.execute(
        "INSERT INTO energy.energy_type_configs "
        "(id, type_code, display_name, unit, sort_order, is_enabled, is_deleted) VALUES "
        "('00000000-0000-0000-0000-000000000001', 'electricity', '电耗数据', 'kWh', 1, true, false),"
        "('00000000-0000-0000-0000-000000000002', 'water',       '水耗数据', 'm³',  2, true, false),"
        "('00000000-0000-0000-0000-000000000003', 'steam',       '蒸汽数据', 't',    3, true, false) "
        "ON CONFLICT (type_code, is_deleted) DO UPDATE SET "
        "display_name = EXCLUDED.display_name, unit = EXCLUDED.unit"
    )


def downgrade() -> None:
    op.execute("DELETE FROM energy.energy_type_configs WHERE type_code IN ('electricity', 'water', 'steam')")
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT IF EXISTS ck_energy_device_config_energy_type"
    )
    op.execute(
        "ALTER TABLE energy.energy_alert_rules "
        "DROP CONSTRAINT IF EXISTS ck_energy_alert_rule_energy_type"
    )
    op.execute(
        "UPDATE energy.energy_device_configs SET energy_type = 'gas' "
        "WHERE energy_type = 'steam'"
    )
    op.execute(
        "UPDATE energy.energy_alert_rules SET energy_type = 'gas' "
        "WHERE energy_type = 'steam'"
    )
    op.create_check_constraint(
        "ck_energy_device_config_energy_type",
        "energy_device_configs",
        "energy_type IN ('electricity', 'water', 'gas')",
        schema="energy",
    )
    op.create_check_constraint(
        "ck_energy_alert_rule_energy_type",
        "energy_alert_rules",
        "energy_type IN ('electricity', 'water', 'gas')",
        schema="energy",
    )
