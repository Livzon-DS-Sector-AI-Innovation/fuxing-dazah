"""Maintenance plan ORM models."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment
    from app.platform.identity.models import User


class MaintenancePlan(BaseModel):
    """维护计划表"""

    __tablename__ = "maintenance_plans"
    __table_args__ = (
        CheckConstraint(
            "plan_type IN ('预防性维护', '预测性维护')",
            name="ck_maintenance_plans_plan_type",
        ),
        CheckConstraint(
            "frequency_unit IN ('天', '周', '月', '年')",
            name="ck_maintenance_plans_frequency_unit",
        ),
        CheckConstraint(
            "status IN ('启用', '停用', '已完成')",
            name="ck_maintenance_plans_status",
        ),
        {"schema": "equipment"},
    )

    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        nullable=True,
        comment="设备ID（与 category_id 二选一）",
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="设备分类ID（与 equipment_id 二选一）",
    )
    plan_name: Mapped[str] = mapped_column(
        String(200), comment="计划名称"
    )
    plan_type: Mapped[str] = mapped_column(
        String(20),
        default="预防性维护",
        comment="计划类型：预防性维护/预测性维护",
    )
    frequency: Mapped[int] = mapped_column(
        Integer, comment="维护频率数值"
    )
    frequency_unit: Mapped[str] = mapped_column(
        String(10), comment="频率单位：天/周/月/年"
    )
    last_maintenance_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="上次维护日期"
    )
    next_maintenance_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="下次维护日期"
    )
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="执行人ID",
    )
    maintenance_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="维护内容说明"
    )
    status: Mapped[str] = mapped_column(
        String(10),
        default="启用",
        server_default="启用",
        comment="状态：启用/停用/已完成",
    )
    remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="备注"
    )
    last_generated_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="最后生成工单的周期日期，用于防重"
    )

    # 关系
    equipment: Mapped[Equipment] = relationship(
        "Equipment",
        foreign_keys=[equipment_id],
    )
    executor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[executor_id],
    )
