"""Inspection ORM models: routes, tasks, photos."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.inspection_template import (
        InspectionTemplate,
    )
    from app.platform.identity.models import User


class InspectionRoute(BaseModel):
    """巡检路线表"""

    __tablename__ = "inspection_routes"
    __table_args__ = (
        UniqueConstraint(
            "name", "is_deleted", name="uq_inspection_routes_name"
        ),
        CheckConstraint(
            "period_type IN ('每日', '每周', '每月', '专项')",
            name="ck_inspection_routes_period_type",
        ),
        {"schema": "equipment"},
    )

    name: Mapped[str] = mapped_column(String(200), comment="路线名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="路线描述"
    )
    area: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="区域"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default="true", comment="是否启用"
    )
    period_type: Mapped[str] = mapped_column(
        String(20), default="每日", comment="巡检周期类型"
    )
    period_value: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="周期数值"
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.inspection_templates.id"),
        nullable=True,
        comment="默认检查模板ID",
    )

    # 关系
    equipments_rel: Mapped[list[InspectionRouteEquipment]] = relationship(
        "InspectionRouteEquipment",
        back_populates="route",
        order_by="InspectionRouteEquipment.sort_order",
    )
    template: Mapped[InspectionTemplate | None] = relationship(
        "InspectionTemplate",
        foreign_keys=[template_id],
    )


class InspectionRouteEquipment(BaseModel):
    """路线-设备关联表"""

    __tablename__ = "inspection_route_equipments"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "equipment_id",
            "is_deleted",
            name="uq_route_equipments_route_equipment",
        ),
        {"schema": "equipment"},
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_routes.id"),
        comment="路线ID",
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        comment="设备ID",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, comment="巡检顺序"
    )

    # 关系
    route: Mapped[InspectionRoute] = relationship(
        back_populates="equipments_rel"
    )
    equipment: Mapped[Equipment] = relationship("Equipment")


class InspectionTask(BaseModel):
    """巡检任务表"""

    __tablename__ = "inspection_tasks"
    __table_args__ = (
        UniqueConstraint(
            "task_no", "is_deleted", name="uq_inspection_tasks_task_no"
        ),
        CheckConstraint(
            "status IN ('待执行', '执行中', '已完成', '已关闭')",
            name="ck_inspection_tasks_status",
        ),
        CheckConstraint(
            "plan_type IN ('线路巡检', '设备巡检')",
            name="ck_inspection_tasks_plan_type",
        ),
        CheckConstraint(
            "overall_result IS NULL OR overall_result IN ('正常', '异常')",
            name="ck_inspection_tasks_overall_result",
        ),
        {"schema": "equipment"},
    )

    task_no: Mapped[str] = mapped_column(
        String(50), comment="任务编号 IT-yyyymmdd-xxxx"
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.inspection_routes.id"),
        nullable=True,
        comment="关联路线ID（路线模式）",
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        nullable=True,
        comment="单设备ID（单设备模式，兼容旧数据）",
    )
    equipment_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="设备ID列表（多设备模式）"
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_templates.id"),
        comment="检查模板ID",
    )
    plan_type: Mapped[str] = mapped_column(
        String(20),
        default="设备巡检",
        comment="巡检类型：线路巡检/设备巡检",
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="巡检人员ID",
    )
    planned_date: Mapped[date] = mapped_column(Date, comment="计划日期")
    status: Mapped[str] = mapped_column(
        String(20),
        default="待执行",
        comment="任务状态：待执行/执行中/已完成/已关闭",
    )
    overall_result: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="总体结果：正常/异常"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="关闭时间"
    )
    closure_remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关闭备注"
    )
    route_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="线路巡检现场描述"
    )

    # 关系
    route: Mapped[InspectionRoute | None] = relationship(
        "InspectionRoute", foreign_keys=[route_id]
    )
    equipment: Mapped[Equipment | None] = relationship(
        "Equipment", foreign_keys=[equipment_id]
    )
    template: Mapped[InspectionTemplate] = relationship(
        "InspectionTemplate", foreign_keys=[template_id]
    )
    assignee: Mapped[User | None] = relationship(
        "User", foreign_keys=[assigned_to]
    )


class InspectionPhoto(BaseModel):
    """巡检到位照片表"""

    __tablename__ = "inspection_photos"
    __table_args__ = ({"schema": "equipment"},)

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_tasks.id"),
        comment="巡检任务ID",
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        nullable=True,
        comment="设备ID（线路巡检时可为空）",
    )
    file_name: Mapped[str] = mapped_column(
        String(255), comment="原始文件名"
    )
    file_path: Mapped[str] = mapped_column(
        String(500), comment="服务器文件路径"
    )
    file_size: Mapped[int | None] = mapped_column(
        comment="文件大小（字节）"
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="上传时间",
    )
