"""Permission API request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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


class UserPermissionOut(BaseModel):
    """用户权限详情（含角色和合并后的权限列表）。"""

    user_id: uuid.UUID
    user_name: str
    roles: list[UserRoleOut]
    permissions: list[str]
    data_scopes: dict[str, str]
    resource_scopes: dict[str, str] = {}
