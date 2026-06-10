"""Energy ORM models: device config, data collection, and collect logs."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID as UUIDType

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class EnergyType(enum.StrEnum):
    ELECTRICITY = "electricity"
    WATER = "water"
    GAS = "gas"


class MonitorLevel(enum.StrEnum):
    NORMAL = "normal"
    IMPORTANT = "important"
    URGENT = "urgent"


class CollectStatus(enum.StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class EnergyDeviceConfig(BaseModel):
    """三方平台设备配置表"""

    __tablename__ = "energy_device_configs"
    __table_args__ = (
        UniqueConstraint(
            "platform_code",
            "platform_device_code",
            "is_deleted",
            name="uq_energy_device_config_platform_device",
        ),
        CheckConstraint(
            "energy_type IN ('electricity', 'water', 'gas')",
            name="ck_energy_device_config_energy_type",
        ),
        CheckConstraint(
            "monitor_level IN ('normal', 'important', 'urgent')",
            name="ck_energy_device_config_monitor_level",
        ),
        CheckConstraint(
            "collection_interval > 0",
            name="ck_energy_device_config_interval_positive",
        ),
        {"schema": "energy"},
    )

    platform_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="平台标识"
    )
    platform_device_code: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="三方平台设备/采集点编码"
    )
    device_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="设备名称"
    )
    energy_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="能源类型: electricity/water/gas"
    )
    api_endpoint: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="API 路径"
    )
    workshop: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="所属车间"
    )
    production_line: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="所属产线"
    )
    monitor_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", comment="监控等级"
    )
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="计量单位"
    )
    collection_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, comment="采集间隔(分钟)"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用采集"
    )
    remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="备注"
    )


class EnergyData(BaseModel):
    """能耗数据采集表"""

    __tablename__ = "energy_data"
    __table_args__ = (
        UniqueConstraint(
            "device_config_id",
            "timestamp",
            name="uq_energy_data_device_timestamp",
        ),
        {"schema": "energy"},
    )

    device_config_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="设备配置ID",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="数据时间点(小时粒度)",
    )
    value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="能耗累计值"
    )
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="计量单位"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="实际采集时间",
    )
    platform_raw_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="原始返回数据"
    )


class EnergyCollectLog(BaseModel):
    """采集日志表"""

    __tablename__ = "energy_collect_logs"
    __table_args__ = ({"schema": "energy"},)

    platform_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="采集的平台"
    )
    collect_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="采集触发时间",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="状态: success/partial/failed"
    )
    device_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="应采集设备数"
    )
    success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="成功条数"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="错误信息"
    )


# ── 预警系统 ──


class AlertLevel(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class MonitorMetric(enum.StrEnum):
    INSTANT = "instant"
    DAILY_TOTAL = "daily_total"
    MONTHLY_TOTAL = "monthly_total"


class ThresholdType(enum.StrEnum):
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EQUAL = "equal"


class NotifyFrequency(enum.StrEnum):
    FIRST = "first"
    EVERY = "every"
    DAILY_SUMMARY = "daily_summary"


class EffectiveTimeType(enum.StrEnum):
    ALL_DAY = "all_day"
    CUSTOM = "custom"


class AlertRecordStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    IGNORED = "ignored"


class EnergyAlertRule(BaseModel):
    """能耗预警规则表"""

    __tablename__ = "energy_alert_rules"
    __table_args__ = (
        CheckConstraint(
            "energy_type IN ('electricity', 'water', 'gas')",
            name="ck_energy_alert_rule_energy_type",
        ),
        CheckConstraint(
            "alert_level IN ('info', 'warning', 'critical', 'emergency')",
            name="ck_energy_alert_rule_alert_level",
        ),
        CheckConstraint(
            "monitor_metric IN ('instant', 'daily_total', 'monthly_total')",
            name="ck_energy_alert_rule_monitor_metric",
        ),
        CheckConstraint(
            "threshold_type IN ('greater_than', 'less_than', 'equal')",
            name="ck_energy_alert_rule_threshold_type",
        ),
        CheckConstraint(
            "notify_frequency IN ('first', 'every', 'daily_summary')",
            name="ck_energy_alert_rule_notify_frequency",
        ),
        CheckConstraint(
            "effective_time IN ('all_day', 'custom')",
            name="ck_energy_alert_rule_effective_time",
        ),
        {"schema": "energy"},
    )

    rule_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="规则名称"
    )
    rule_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="规则描述"
    )
    energy_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="能源类型"
    )
    monitor_metric: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="监控指标: instant/daily_total/monthly_total"
    )
    threshold_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="阈值类型"
    )
    threshold_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="阈值"
    )
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="计量单位"
    )
    alert_level: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="预警等级"
    )
    notify_method: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, comment="通知方式: email/sms/feishu"
    )
    notify_users: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, comment="通知用户列表"
    )
    notify_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default="first", comment="通知频率"
    )
    effective_time: Mapped[str] = mapped_column(
        String(20), nullable=False, default="all_day", comment="生效时段类型"
    )
    custom_time_start: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="自定义开始时间(HH:MM:SS)"
    )
    custom_time_end: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="自定义结束时间(HH:MM:SS)"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用"
    )


class EnergyAlertRecord(BaseModel):
    """预警记录表"""

    __tablename__ = "energy_alert_records"
    __table_args__ = (
        CheckConstraint(
            "alert_level IN ('info', 'warning', 'critical', 'emergency')",
            name="ck_energy_alert_record_alert_level",
        ),
        CheckConstraint(
            "status IN ('pending', 'processed', 'ignored')",
            name="ck_energy_alert_record_status",
        ),
        {"schema": "energy"},
    )

    rule_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("energy.energy_alert_rules.id", ondelete="CASCADE"),
        nullable=False,
        comment="预警规则ID",
    )
    device_config_id: Mapped[UUIDType | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联设备配置ID",
    )
    energy_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="能源类型"
    )
    alert_level: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="预警等级"
    )
    trigger_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="触发值"
    )
    threshold_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="阈值"
    )
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="计量单位"
    )
    alert_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="预警触发时间"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="处理状态"
    )
    processed_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="处理人"
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理时间"
    )
    process_note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处理备注"
    )
