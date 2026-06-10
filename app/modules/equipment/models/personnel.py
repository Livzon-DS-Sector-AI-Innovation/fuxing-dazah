"""Equipment personnel ORM models."""

import uuid as _uuid

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class EquipmentRole(BaseModel):
    """设备模块 — 角色定义"""

    __tablename__ = "equipment_role"
    __table_args__ = (
        UniqueConstraint("code", name="uq_equipment_role_code"),
        Index("ix_equipment_role_scope_deleted", "scope", "is_deleted"),
        {"schema": "equipment"},
    )

    name: Mapped[str] = mapped_column(String(100), comment="角色名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, comment="角色编码")
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="角色描述"
    )
    scope: Mapped[str] = mapped_column(
        String(50), default="global", server_default="'global'", comment="作用域"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用"
    )


class EquipmentPersonnel(BaseModel):
    """设备模块 — 人员池"""

    __tablename__ = "equipment_personnel"
    __table_args__ = (
        Index("ix_equipment_personnel_user_id", "user_id"),
        Index("ix_equipment_personnel_feishu_user_id", "feishu_user_id"),
        Index("ix_equipment_personnel_name", "name"),
        {"schema": "equipment"},
    )

    user_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="逻辑引用 identity.users.id"
    )
    name: Mapped[str] = mapped_column(String(100), comment="冗余，人员姓名")
    employee_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="冗余，工号"
    )
    department: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="冗余，部门"
    )
    feishu_user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书 user_id（发消息通知用）"
    )
    feishu_open_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书 open_id"
    )
    mobile: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="冗余，手机号"
    )
    extended_attrs: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="扩展属性槽"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否在岗"
    )


class EquipmentPersonnelRole(BaseModel):
    """设备模块 — 人员角色关联"""

    __tablename__ = "equipment_personnel_role"
    __table_args__ = (
        UniqueConstraint(
            "personnel_id", "role_id",
            name="uq_equipment_personnel_role",
        ),
        {"schema": "equipment"},
    )

    personnel_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="逻辑引用 equipment_personnel.id"
    )
    role_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="逻辑引用 equipment_role.id"
    )


class EquipmentPersonnelCategory(BaseModel):
    """设备模块 — 人员+角色绑定设备分类"""

    __tablename__ = "equipment_personnel_category"
    __table_args__ = (
        UniqueConstraint(
            "personnel_id", "role_id", "category_id",
            name="uq_equipment_personnel_category",
        ),
        {"schema": "equipment"},
    )

    personnel_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="逻辑引用 equipment_personnel.id"
    )
    role_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="逻辑引用 equipment_role.id"
    )
    category_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="逻辑引用 equipment_categories.id"
    )
