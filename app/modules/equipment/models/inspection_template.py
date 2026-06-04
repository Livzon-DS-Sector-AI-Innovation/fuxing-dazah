"""Inspection template ORM models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.work_order import WorkOrder


class InspectionTemplate(BaseModel):
    """巡检模板表"""

    __tablename__ = "inspection_templates"
    __table_args__ = (
        {"schema": "equipment"},
    )

    name: Mapped[str] = mapped_column(
        String(200), comment="模板名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="模板描述"
    )
    equipment_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.equipment_categories.id"),
        nullable=True,
        comment="适用设备分类ID",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
        comment="是否启用",
    )

    # 关系
    items: Mapped[list[InspectionTemplateItem]] = relationship(
        "InspectionTemplateItem",
        back_populates="template",
        order_by="InspectionTemplateItem.sort_order",
    )


class InspectionTemplateItem(BaseModel):
    """巡检模板检查项表"""

    __tablename__ = "inspection_template_items"
    __table_args__ = (
        {"schema": "equipment"},
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_templates.id"),
        comment="模板ID",
    )
    item_name: Mapped[str] = mapped_column(
        String(200), comment="检查项名称"
    )
    item_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="检查项说明"
    )
    expected_result: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="预期结果/标准值"
    )
    check_method: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检查方法"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="排序序号"
    )

    # 关系
    template: Mapped[InspectionTemplate] = relationship(
        "InspectionTemplate",
        back_populates="items",
    )


class InspectionRecord(BaseModel):
    """巡检记录明细表"""

    __tablename__ = "inspection_records"
    __table_args__ = (
        {"schema": "equipment"},
    )

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.work_orders.id"),
        comment="关联巡检工单ID",
    )
    template_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_template_items.id"),
        comment="检查项ID",
    )
    result: Mapped[str] = mapped_column(
        String(20), comment="结果：正常/异常/跳过"
    )
    actual_value: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="实际值"
    )
    remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="备注"
    )

    # 关系
    work_order: Mapped[WorkOrder] = relationship("WorkOrder")
    template_item: Mapped[InspectionTemplateItem] = relationship(
        "InspectionTemplateItem"
    )
