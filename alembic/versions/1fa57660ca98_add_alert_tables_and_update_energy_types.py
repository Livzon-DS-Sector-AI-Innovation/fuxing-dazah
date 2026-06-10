"""add alert tables and update energy types

Revision ID: 1fa57660ca98
Revises: 62d4ceac12b4
Create Date: 2026-06-08 09:52:22.359516
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1fa57660ca98'
down_revision: Union[str, None] = '62d4ceac12b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. 更新 CHECK 约束: steam → gas ──
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT ck_energy_device_config_energy_type"
    )
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "ADD CONSTRAINT ck_energy_device_config_energy_type "
        "CHECK (energy_type IN ('electricity', 'water', 'gas'))"
    )

    # ── 2. energy_alert_rules ──
    op.create_table(
        "energy_alert_rules",
        sa.Column("rule_name", sa.String(200), nullable=False,
                  comment="规则名称"),
        sa.Column("rule_description", sa.Text(), nullable=True,
                  comment="规则描述"),
        sa.Column("energy_type", sa.String(20), nullable=False,
                  comment="能源类型"),
        sa.Column("monitor_metric", sa.String(20), nullable=False,
                  comment="监控指标"),
        sa.Column("threshold_type", sa.String(20), nullable=False,
                  comment="阈值类型"),
        sa.Column("threshold_value", sa.Numeric(18, 4), nullable=False,
                  comment="阈值"),
        sa.Column("unit", sa.String(20), nullable=False,
                  comment="计量单位"),
        sa.Column("alert_level", sa.String(20), nullable=False,
                  comment="预警等级"),
        sa.Column("notify_method", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, comment="通知方式"),
        sa.Column("notify_users", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, comment="通知用户列表"),
        sa.Column("notify_frequency", sa.String(20), nullable=False,
                  comment="通知频率"),
        sa.Column("effective_time", sa.String(20), nullable=False,
                  comment="生效时段类型"),
        sa.Column("custom_time_start", sa.String(8), nullable=True,
                  comment="自定义开始时间"),
        sa.Column("custom_time_end", sa.String(8), nullable=True,
                  comment="自定义结束时间"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False,
                  comment="是否启用"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false",
                  nullable=False),
        sa.CheckConstraint(
            "energy_type IN ('electricity', 'water', 'gas')",
            name="ck_energy_alert_rule_energy_type",
        ),
        sa.CheckConstraint(
            "alert_level IN ('info', 'warning', 'critical', 'emergency')",
            name="ck_energy_alert_rule_alert_level",
        ),
        sa.CheckConstraint(
            "monitor_metric IN ('instant', 'daily_total', 'monthly_total')",
            name="ck_energy_alert_rule_monitor_metric",
        ),
        sa.CheckConstraint(
            "threshold_type IN ('greater_than', 'less_than', 'equal')",
            name="ck_energy_alert_rule_threshold_type",
        ),
        sa.CheckConstraint(
            "notify_frequency IN ('first', 'every', 'daily_summary')",
            name="ck_energy_alert_rule_notify_frequency",
        ),
        sa.CheckConstraint(
            "effective_time IN ('all_day', 'custom')",
            name="ck_energy_alert_rule_effective_time",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="energy",
    )

    # ── 3. energy_alert_records ──
    op.create_table(
        "energy_alert_records",
        sa.Column("rule_id", sa.Uuid(), nullable=False,
                  comment="预警规则ID"),
        sa.Column("device_config_id", sa.Uuid(), nullable=True,
                  comment="关联设备配置ID"),
        sa.Column("energy_type", sa.String(20), nullable=False,
                  comment="能源类型"),
        sa.Column("alert_level", sa.String(20), nullable=False,
                  comment="预警等级"),
        sa.Column("trigger_value", sa.Numeric(18, 4), nullable=False,
                  comment="触发值"),
        sa.Column("threshold_value", sa.Numeric(18, 4), nullable=False,
                  comment="阈值"),
        sa.Column("unit", sa.String(20), nullable=False,
                  comment="计量单位"),
        sa.Column("alert_time", sa.DateTime(timezone=True), nullable=False,
                  comment="预警触发时间"),
        sa.Column("status", sa.String(20), nullable=False,
                  comment="处理状态"),
        sa.Column("processed_by", sa.String(100), nullable=True,
                  comment="处理人"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True,
                  comment="处理时间"),
        sa.Column("process_note", sa.Text(), nullable=True,
                  comment="处理备注"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false",
                  nullable=False),
        sa.CheckConstraint(
            "alert_level IN ('info', 'warning', 'critical', 'emergency')",
            name="ck_energy_alert_record_alert_level",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processed', 'ignored')",
            name="ck_energy_alert_record_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["energy.energy_alert_rules.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="energy",
    )


def downgrade() -> None:
    op.drop_table("energy_alert_records", schema="energy")
    op.drop_table("energy_alert_rules", schema="energy")
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "DROP CONSTRAINT ck_energy_device_config_energy_type"
    )
    op.execute(
        "ALTER TABLE energy.energy_device_configs "
        "ADD CONSTRAINT ck_energy_device_config_energy_type "
        "CHECK (energy_type IN ('electricity', 'steam', 'water'))"
    )
