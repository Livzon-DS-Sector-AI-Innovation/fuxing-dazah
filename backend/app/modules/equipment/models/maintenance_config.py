"""Maintenance config ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class MaintenanceConfig(BaseModel):
    """维护配置表"""

    __tablename__ = "maintenance_config"
    __table_args__ = {"schema": "equipment"}

    config_key: Mapped[str] = mapped_column(String(100), unique=True, comment="配置键")
    config_value: Mapped[str] = mapped_column(String(500), comment="配置值")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
