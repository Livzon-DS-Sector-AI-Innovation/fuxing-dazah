"""Inspection route location ORM models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.equipment.models.equipment import Equipment, Location
    from app.modules.equipment.models.inspection import InspectionRoute
    from app.modules.equipment.models.inspection_template import (
        InspectionTemplate,
    )


class RouteLocation(BaseModel):
    """线路-地点关联表"""

    __tablename__ = "route_locations"
    __table_args__ = (
        Index(
            "uq_route_locations_active",
            "route_id",
            "location_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_routes.id"), comment="路线ID"
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.locations.id"), comment="地点ID"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="地点巡检顺序"
    )

    # 关系
    route: Mapped[InspectionRoute] = relationship(
        "InspectionRoute", back_populates="locations_rel"
    )
    equipments: Mapped[list[RouteLocationEquipment]] = relationship(
        "RouteLocationEquipment",
        back_populates="route_location",
        order_by="RouteLocationEquipment.sort_order",
        primaryjoin=(
            "and_(RouteLocation.id =="
            " foreign(RouteLocationEquipment.route_location_id), "
            "RouteLocationEquipment.is_deleted == False)"
        ),
    )
    location: Mapped[Location] = relationship("Location")


class RouteLocationEquipment(BaseModel):
    """线路地点-设备关联表"""

    __tablename__ = "route_location_equipments"
    __table_args__ = (
        Index(
            "uq_route_location_equipments_active",
            "route_location_id",
            "equipment_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    route_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.route_locations.id"), comment="线路地点ID"
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.equipments.id"), comment="设备ID"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="地点内设备顺序"
    )

    # 关系
    route_location: Mapped[RouteLocation] = relationship(
        "RouteLocation", back_populates="equipments"
    )
    equipment: Mapped[Equipment] = relationship("Equipment")
    templates_rel: Mapped[list[RouteEquipmentTemplate]] = relationship(
        "RouteEquipmentTemplate",
        back_populates="route_equipment",
        primaryjoin=(
            "and_(RouteLocationEquipment.id =="
            " foreign(RouteEquipmentTemplate.route_equipment_id), "
            "RouteEquipmentTemplate.is_deleted == False)"
        ),
    )


class RouteEquipmentTemplate(BaseModel):
    """设备-模板绑定表"""

    __tablename__ = "route_equipment_templates"
    __table_args__ = (
        Index(
            "uq_route_equipment_templates_active",
            "route_equipment_id",
            "template_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    route_equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.route_location_equipments.id"), comment="线路地点设备ID"
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.inspection_templates.id"), comment="巡检模板ID"
    )

    # 关系
    route_equipment: Mapped[RouteLocationEquipment] = relationship(
        "RouteLocationEquipment", back_populates="templates_rel"
    )
    template: Mapped[InspectionTemplate] = relationship(
        "InspectionTemplate"
    )
