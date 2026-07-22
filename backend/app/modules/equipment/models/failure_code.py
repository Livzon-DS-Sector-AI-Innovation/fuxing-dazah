"""Failure code ORM models."""

from sqlalchemy import Boolean, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class FailureSymptom(BaseModel):
    """故障现象表"""

    __tablename__ = "failure_symptoms"
    __table_args__ = (
        Index(
            "uq_failure_symptoms_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    code: Mapped[str] = mapped_column(
        String(50), comment="故障现象代码"
    )
    name: Mapped[str] = mapped_column(
        String(100), comment="故障现象名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="故障现象描述"
    )
    sort_order: Mapped[int] = mapped_column(
        default=0, comment="排序号"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        comment="是否启用",
    )


class FailureCause(BaseModel):
    """故障原因表"""

    __tablename__ = "failure_causes"
    __table_args__ = (
        Index(
            "uq_failure_causes_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    code: Mapped[str] = mapped_column(
        String(50), comment="故障原因代码"
    )
    name: Mapped[str] = mapped_column(
        String(100), comment="故障原因名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="故障原因描述"
    )
    sort_order: Mapped[int] = mapped_column(
        default=0, comment="排序号"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        comment="是否启用",
    )


class FailureAction(BaseModel):
    """维修措施表"""

    __tablename__ = "failure_actions"
    __table_args__ = (
        Index(
            "uq_failure_actions_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "equipment"},
    )

    code: Mapped[str] = mapped_column(
        String(50), comment="维修措施代码"
    )
    name: Mapped[str] = mapped_column(
        String(100), comment="维修措施名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="维修措施描述"
    )
    sort_order: Mapped[int] = mapped_column(
        default=0, comment="排序号"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        comment="是否启用",
    )
