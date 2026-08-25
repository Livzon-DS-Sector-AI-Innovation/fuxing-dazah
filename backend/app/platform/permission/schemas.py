"""Permission API request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── 权限 ──


class PermissionOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    module: str
    resource: str
    action: str
    description: str | None = None
    is_system: bool

    model_config = {"from_attributes": True}


class PermissionModuleGroup(BaseModel):
    """按模块分组的权限列表。"""

    module: str
    module_name: str
    permissions: list[PermissionOut]


# ── 角色 ──


class CreateRoleInput(BaseModel):
    code: str = Field(..., max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., max_length=100)
    description: str | None = None
    data_scope: str = Field(
        default="department",
        pattern=r"^(all|department|department_and_children|self_only)$",
    )
    permission_ids: list[uuid.UUID] = []
    data_scope_overrides: dict[str, str] = {}


class UpdateRoleInput(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = None
    data_scope: str | None = Field(
        default=None, pattern=r"^(all|department|department_and_children|self_only)$"
    )
    permission_ids: list[uuid.UUID] | None = None
    data_scope_overrides: dict[str, str] | None = None


class RoleOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    data_scope: str
    is_system: bool
    created_at: datetime
    updated_at: datetime
    permission_ids: list[uuid.UUID] = []
    data_scope_overrides: dict[str, str] = {}
    user_count: int = 0
    department_count: int = 0


# ── 用户角色 ──


class AssignRoleInput(BaseModel):
    role_id: uuid.UUID
    department_id: uuid.UUID | None = None


class UserRoleOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    department_id: uuid.UUID | None
    role_name: str = ""
    role_code: str = ""


class RoleUserOut(BaseModel):
    """角色下的用户（角色分配弹窗展示用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    employee_no: str | None = None
    department: str | None = None
    position: str | None = None
    avatar_url: str | None = None


class UserPermissionOut(BaseModel):
    """用户权限详情（含角色和合并后的权限列表）。"""

    user_id: uuid.UUID
    user_name: str
    roles: list[UserRoleOut]
    permissions: list[str]
    data_scopes: dict[str, str]
    resource_scopes: dict[str, str] = {}


# ── 部门角色 ──


class AssignDepartmentRoleInput(BaseModel):
    """将角色分配给一个或多个部门。"""

    feishu_department_ids: list[str] = Field(
        ..., min_length=1, description="飞书部门 ID 列表"
    )


class DepartmentRoleOut(BaseModel):
    """部门角色关联（含部门名称和成员数）。"""

    id: uuid.UUID
    feishu_department_id: str
    role_id: uuid.UUID
    department_name: str = ""
    member_count: int = 0

    model_config = {"from_attributes": True}
