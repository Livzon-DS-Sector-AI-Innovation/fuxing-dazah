"""Work order ORM model."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.failure_code import (
        FailureAction,
        FailureCause,
        FailureSymptom,
    )
    from app.modules.equipment.models.work_order_image import WorkOrderImage
    from app.platform.identity.models import User


class WorkOrder(BaseModel):
    """维修工单表"""

    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint(
            "work_order_no",
            "is_deleted",
            name="uq_work_orders_work_order_no",
        ),
        CheckConstraint(
            "order_type IN ('故障维修', '计划维护', '巡检', '校准', '异常处理', '日常维护')",
            name="ck_work_orders_order_type",
        ),
        CheckConstraint(
            "priority IN ('紧急', '高', '中', '低')",
            name="ck_work_orders_priority",
        ),
        CheckConstraint(
            "status IN ('待处理', '执行中', '待验收', '已完成', '已关闭')",
            name="ck_work_orders_status",
        ),
        CheckConstraint(
            "verification_result IS NULL OR verification_result IN ('合格', '不合格')",
            name="ck_work_orders_verification_result",
        ),
        {"schema": "equipment"},
    )

    work_order_no: Mapped[str] = mapped_column(
        String(50), comment="工单编号"
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        comment="设备ID",
    )
    order_type: Mapped[str] = mapped_column(
        String(20), comment="工单类型：故障维修/计划维护/巡检/校准/异常处理/日常维护"
    )
    responsible_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="责任人ID",
    )
    priority: Mapped[str] = mapped_column(
        String(10),
        default="中",
        comment="优先级：紧急/高/中/低",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="待处理",
        comment="状态：待处理/执行中/待验收/已完成/已关闭",
    )
    fault_symptom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.failure_symptoms.id"),
        nullable=True,
        comment="故障现象ID",
    )
    fault_cause_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.failure_causes.id"),
        nullable=True,
        comment="故障原因ID",
    )
    fault_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.failure_actions.id"),
        nullable=True,
        comment="维修措施ID",
    )
    fault_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="故障描述"
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="报修人ID，系统自动生成的工单可为空",
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="指派人ID",
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("identity.users.id"),
        nullable=True,
        comment="验收人ID",
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="报修时间",
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="指派时间",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始维修时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="验收时间",
    )
    verification_result: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="验收结果：合格/不合格",
    )
    verification_remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="验收备注"
    )
    repair_detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="维修详情"
    )
    actual_duration: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="实际用时（分钟）",
    )
    original_equipment_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="创建工单时的设备原始状态",
    )
    maintenance_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.maintenance_plans.id"),
        nullable=True,
        comment="关联维护计划ID",
    )
    planned_start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="计划执行日期"
    )
    checklist_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.inspection_templates.id"),
        nullable=True,
        comment="关联巡检模板ID",
    )
    check_result: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="巡检结果：正常/异常"
    )
    spare_parts_cost: Mapped[float | None] = mapped_column(
        nullable=True, comment="备件费用汇总"
    )
    inspection_task_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="来源巡检任务ID，由巡检异常自动创建时填入"
    )

    # 关系
    equipment: Mapped[Equipment] = relationship(
        "Equipment",
        foreign_keys=[equipment_id],
    )
    fault_symptom: Mapped[FailureSymptom | None] = relationship(
        "FailureSymptom",
        foreign_keys=[fault_symptom_id],
    )
    fault_cause: Mapped[FailureCause | None] = relationship(
        "FailureCause",
        foreign_keys=[fault_cause_id],
    )
    fault_action: Mapped[FailureAction | None] = relationship(
        "FailureAction",
        foreign_keys=[fault_action_id],
    )
    reporter: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reporter_id],
    )
    assignee: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assignee_id],
    )
    responsible_person: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[responsible_person_id],
    )
    images: Mapped[list[WorkOrderImage]] = relationship(
        "WorkOrderImage",
        foreign_keys="WorkOrderImage.work_order_id",
        primaryjoin="and_(WorkOrder.id == foreign(WorkOrderImage.work_order_id), WorkOrderImage.is_deleted == False)",
        lazy="selectin",
    )
