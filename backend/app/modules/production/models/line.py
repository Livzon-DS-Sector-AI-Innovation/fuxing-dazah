"""产线字典与用户-产线绑定 ORM。"""

import uuid

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Line(BaseModel):
    """产线字典 —— 实际执行工艺路线的物理产线，与工艺路线不建立绑定关系。"""

    __tablename__ = "lines"
    __table_args__ = (
        Index(
            "uq_production_lines_name",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    name: Mapped[str] = mapped_column(String(200), comment="产线名称")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class LineAssignment(BaseModel):
    """用户-产线绑定（不限身份，负责人、执行人均可绑定）"""

    __tablename__ = "line_assignments"
    __table_args__ = (
        Index(
            "uq_production_line_assignments",
            "user_id",
            "line_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_line_assignments_user", "user_id"),
        Index("ix_production_line_assignments_line", "line_id"),
        {"schema": "production"},
    )

    user_id: Mapped[uuid.UUID]
    line_id: Mapped[uuid.UUID]


class LineProductLink(BaseModel):
    """产线-产品关联（多对多，主数据展示用途）"""

    __tablename__ = "line_product_links"
    __table_args__ = (
        Index(
            "uq_production_line_product_links",
            "line_id",
            "product_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_line_product_links_line", "line_id"),
        Index("ix_production_line_product_links_product", "product_id"),
        {"schema": "production"},
    )

    line_id: Mapped[uuid.UUID]
    product_id: Mapped[uuid.UUID]
