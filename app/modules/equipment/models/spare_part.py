"""Spare part ORM models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.work_order import WorkOrder


class SparePart(BaseModel):
    """备件主数据表"""

    __tablename__ = "spare_parts"
    __table_args__ = (
        Index(
            "uq_spare_parts_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    code: Mapped[str] = mapped_column(
        String(50), comment="备件编码"
    )
    name: Mapped[str] = mapped_column(
        String(200), comment="备件名称"
    )
    specification: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="规格型号"
    )
    unit: Mapped[str] = mapped_column(
        String(20), comment="计量单位"
    )
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="备件分类"
    )
    default_supplier: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="默认供应商"
    )
    unit_price: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True, comment="参考单价"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        comment="是否启用",
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="归属部门ID，逻辑引用 identity.departments.id"
    )


class EquipmentSparePart(BaseModel):
    """设备-备件关联表"""

    __tablename__ = "equipment_spare_parts"
    __table_args__ = (
        Index(
            "uq_equipment_spare_parts_eq_sp",
            "equipment_id",
            "spare_part_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.equipments.id"),
        comment="设备ID",
    )
    spare_part_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.spare_parts.id"),
        comment="备件ID",
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=1, comment="该设备需要的数量"
    )

    equipment: Mapped[Equipment] = relationship("Equipment")
    spare_part: Mapped[SparePart] = relationship("SparePart")


class SparePartStock(BaseModel):
    """备件库存表"""

    __tablename__ = "spare_part_stocks"
    __table_args__ = (
        {"schema": "equipment"},
    )

    spare_part_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.spare_parts.id"),
        unique=True,
        comment="备件ID",
    )
    warehouse_location: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="库位"
    )
    current_qty: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="当前库存"
    )
    safety_qty: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="安全库存"
    )
    min_order_qty: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="最小采购批量"
    )

    spare_part: Mapped[SparePart] = relationship("SparePart")


class SparePartTransaction(BaseModel):
    """备件库存流水表"""

    __tablename__ = "spare_part_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('入库', '出库', '盘点调整')",
            name="ck_spare_part_transactions_type",
        ),
        {"schema": "equipment"},
    )

    spare_part_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.spare_parts.id"),
        comment="备件ID",
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.work_orders.id"),
        nullable=True,
        comment="关联工单ID",
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20), comment="类型：入库/出库/盘点调整"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, comment="数量（正=入库，负=出库）"
    )
    remark: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="备注"
    )

    spare_part: Mapped[SparePart] = relationship("SparePart")
    work_order: Mapped[WorkOrder | None] = relationship("WorkOrder")
