"""工段节点负责人分配 ORM。"""

import uuid

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class StageAssignment(BaseModel):
    """工段负责人分配"""

    __tablename__ = "stage_assignments"
    __table_args__ = (
        Index(
            "uq_production_stage_assignments",
            "user_id",
            "stage_name",
            "route_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_stage_assignments_user", "user_id"),
        Index("ix_production_stage_assignments_route", "route_id"),
        {"schema": "production"},
    )

    user_id: Mapped[uuid.UUID]
    stage_name: Mapped[str] = mapped_column(String(100))
    route_id: Mapped[uuid.UUID]


class NodeAssignment(BaseModel):
    """工序节点负责人分配"""

    __tablename__ = "node_assignments"
    __table_args__ = (
        Index(
            "uq_production_node_assignments",
            "user_id",
            "node_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_node_assignments_user", "user_id"),
        Index("ix_production_node_assignments_node", "node_id"),
        {"schema": "production"},
    )

    user_id: Mapped[uuid.UUID]
    node_id: Mapped[uuid.UUID]
    route_id: Mapped[uuid.UUID]
    assigned_by: Mapped[uuid.UUID]
