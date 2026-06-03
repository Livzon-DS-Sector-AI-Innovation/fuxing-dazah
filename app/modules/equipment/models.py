"""Equipment ORM models."""

import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel


class EquipmentCategory(BaseModel):
    """设备分类表"""

    __tablename__ = "equipment_categories"
    __table_args__ = (
        UniqueConstraint(
            "code", "is_deleted", name="uq_equipment_categories_code"
        ),
        {"schema": "equipment"},
    )

    name: Mapped[str] = mapped_column(
        String(100), comment="分类名称"
    )
    code: Mapped[str] = mapped_column(
        String(50), comment="分类代码"
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.equipment_categories.id"),
        nullable=True,
        comment="父分类ID",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="分类描述"
    )

    # 关系
    parent: Mapped["EquipmentCategory | None"] = relationship(
        "EquipmentCategory",
        remote_side="EquipmentCategory.id",
        back_populates="children",
    )
    children: Mapped[list["EquipmentCategory"]] = relationship(
        "EquipmentCategory",
        back_populates="parent",
    )


class Location(BaseModel):
    """位置表"""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint(
            "code", "is_deleted", name="uq_locations_code"
        ),
        {"schema": "equipment"},
    )

    name: Mapped[str] = mapped_column(
        String(100), comment="位置名称"
    )
    code: Mapped[str] = mapped_column(
        String(50), comment="位置代码"
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.locations.id"),
        nullable=True,
        comment="父位置ID",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="位置描述"
    )

    # 关系
    parent: Mapped["Location | None"] = relationship(
        "Location",
        remote_side="Location.id",
        back_populates="children",
    )
    children: Mapped[list["Location"]] = relationship(
        "Location",
        back_populates="parent",
    )


class Equipment(BaseModel):
    """设备主表"""

    __tablename__ = "equipments"
    __table_args__ = (
        UniqueConstraint(
            "equipment_no", "is_deleted", name="uq_equipments_equipment_no"
        ),
        CheckConstraint(
            "status IN ('在用', '备用', '维修中', '停用', '报废')",
            name="ck_equipments_status",
        ),
        {"schema": "equipment"},
    )

    equipment_no: Mapped[str] = mapped_column(
        String(50), comment="设备编号"
    )
    name: Mapped[str] = mapped_column(
        String(200), comment="设备名称"
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.equipment_categories.id"),
        comment="设备分类",
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.locations.id"),
        comment="设备位置",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="在用",
        comment="设备状态：在用/备用/维修中/停用/报废",
    )
    model: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="设备型号"
    )
    specification: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="设备规格"
    )
    manufacturer: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="制造商"
    )
    supplier: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="供应商"
    )
    production_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="出厂日期"
    )
    commissioning_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="投用日期"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="设备描述"
    )

    # 关系
    category: Mapped["EquipmentCategory"] = relationship(
        "EquipmentCategory"
    )
    location: Mapped["Location"] = relationship("Location")
