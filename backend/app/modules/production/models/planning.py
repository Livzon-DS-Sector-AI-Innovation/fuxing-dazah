"""生产计划 ORM：需求 / 计划单 / 计划项 / 分配关系。"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Demand(BaseModel):
    """需求条目：销售订单、手动录入、预测等需求的统一载体。"""

    __tablename__ = "demands"
    __table_args__ = (
        Index(
            "uq_production_demands_no",
            "demand_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "source_type IN ('manual', 'sales_order', 'forecast', 'internal')",
            name="ck_production_demands_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'partial', 'fulfilled', 'closed', 'cancelled')",
            name="ck_production_demands_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_demands_priority",
        ),
        {"schema": "production"},
    )

    demand_no: Mapped[str] = mapped_column(String(30), comment="需求编号")
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual", comment="manual/sales_order/forecast/internal"
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="外部来源引用号"
    )
    product_id: Mapped[uuid.UUID] = mapped_column(comment="产品")
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名快照")
    demanded_quantity: Mapped[float] = mapped_column(Float, comment="原始需求量")
    allocated_quantity: Mapped[float] = mapped_column(
        Float, default=0, comment="已分配量"
    )
    fulfilled_quantity: Mapped[float] = mapped_column(
        Float, default=0, comment="已完成量"
    )
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    demand_date: Mapped[date] = mapped_column(Date, comment="需求日期")
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="pending/confirmed/partial/fulfilled/closed/cancelled"
    )
    customer_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="客户名称"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanOrder(BaseModel):
    """计划单：将需求转化为生产计划的决策载体。"""

    __tablename__ = "plan_orders"
    __table_args__ = (
        Index(
            "uq_production_plan_orders_no",
            "order_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'released', 'completed', 'closed')",
            name="ck_production_plan_orders_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_plan_orders_priority",
        ),
        {"schema": "production"},
    )

    order_no: Mapped[str] = mapped_column(String(30), comment="计划单号")
    title: Mapped[str] = mapped_column(String(200), comment="计划标题")
    plan_version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft/confirmed/released/completed/closed"
    )
    scheduled_start: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="计划开始日期"
    )
    scheduled_end: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="计划结束日期"
    )
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanItem(BaseModel):
    """计划项：排程最小单元。"""

    __tablename__ = "plan_items"
    __table_args__ = (
        Index(
            "uq_production_plan_items_no",
            "plan_order_id",
            "item_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_production_plan_items_equipment_time",
            "equipment_id",
            "planned_start",
            "planned_end",
        ),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'allocated', 'in_progress', 'completed', 'cancelled')",
            name="ck_production_plan_items_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_plan_items_priority",
        ),
        {"schema": "production"},
    )

    plan_order_id: Mapped[uuid.UUID] = mapped_column(comment="所属计划单")
    item_no: Mapped[int] = mapped_column(Integer, comment="计划单内序号")
    intermediate_type_id: Mapped[uuid.UUID] = mapped_column(comment="产出物（中间体类型）")
    intermediate_type_name: Mapped[str] = mapped_column(String(200), comment="产出物名称快照")
    route_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="工艺路线")
    equipment_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="目标设备/产线"
    )
    planned_quantity: Mapped[float] = mapped_column(Float, comment="计划产量")
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    planned_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft/scheduled/allocated/in_progress/completed/cancelled"
    )
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排程序号")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanAllocation(BaseModel):
    """计划项↔批次分配关系（纯映射，无生命周期）。"""

    __tablename__ = "plan_allocations"
    __table_args__ = (
        Index(
            "uq_production_plan_allocations",
            "plan_item_id",
            "batch_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    plan_item_id: Mapped[uuid.UUID] = mapped_column(comment="计划项")
    batch_id: Mapped[uuid.UUID] = mapped_column(comment="批次")
    allocated_quantity: Mapped[float] = mapped_column(Float, comment="本批次承担数量")


class DemandAllocation(BaseModel):
    """需求↔计划项关联（纯映射）。"""

    __tablename__ = "demand_allocations"
    __table_args__ = (
        Index(
            "uq_production_demand_allocations",
            "demand_id",
            "plan_item_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    demand_id: Mapped[uuid.UUID] = mapped_column(comment="需求")
    plan_item_id: Mapped[uuid.UUID] = mapped_column(comment="计划项")
    allocated_quantity: Mapped[float] = mapped_column(Float, comment="该计划项为此需求承担的数量")
