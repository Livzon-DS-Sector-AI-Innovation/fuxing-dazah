"""Permission system ORM models."""

import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Permission(BaseModel):
    """权限定义表：每条记录对应一个功能点。"""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_permission_permissions_code"),
        {"schema": "permission"},
    )

    code: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        comment="权限编码，如 equipment:inspection:create",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="显示名称，如 创建巡检",
    )
    module: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="所属模块编码"
    )
    resource: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="资源类型"
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="操作类型: read/create/update/delete/approve/manage",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="系统内置权限不可删除",
    )


class Role(BaseModel):
    """角色表。"""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("code", name="uq_permission_roles_code"),
        {"schema": "permission"},
    )

    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="角色编码，如 equipment_inspector",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="显示名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_scope: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="department",
        comment="默认数据范围: all/department/department_and_children/self_only",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="系统内置角色不可删除",
    )


class RolePermission(BaseModel):
    """角色-权限关联表。"""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),
        {"schema": "permission"},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="角色 ID"
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="权限 ID"
    )


class UserRole(BaseModel):
    """用户-角色关联表。"""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            "department_id",
            name="uq_user_roles_triple",
        ),
        {"schema": "permission"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="用户 ID (identity.users)"
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="角色 ID"
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="可选：限定角色在某部门生效，NULL=全局",
    )


class RoleDataScopeOverride(BaseModel):
    """角色在特定模块的数据范围覆盖。"""

    __tablename__ = "role_data_scope_overrides"
    __table_args__ = (
        UniqueConstraint("role_id", "module", name="uq_role_data_scope_module"),
        {"schema": "permission"},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="角色 ID"
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False, comment="模块编码")
    data_scope: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="覆盖后的数据范围",
    )
