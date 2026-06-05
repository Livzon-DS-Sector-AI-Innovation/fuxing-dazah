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
    STEAM = "steam"
    WATER = "water"


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
            "energy_type IN ('electricity', 'steam', 'water')",
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
        String(20), nullable=False, comment="能源类型: electricity/steam/water"
    )
    api_endpoint: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="API 路径"
    )
    workshop: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="所属车间"
    )
    production_line: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="所属产线"
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
