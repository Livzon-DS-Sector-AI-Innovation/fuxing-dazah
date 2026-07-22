"""Equipment personnel schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── 角色 Schema ──

class RoleCreate(BaseModel):
    """创建角色请求"""

    name: str = Field(..., min_length=1, max_length=100, description="角色名称")
    code: str = Field(..., min_length=1, max_length=50, description="角色编码")
    description: str | None = Field(None, max_length=200, description="角色描述")
    scope: str = Field(default="global", description="作用域")
    is_active: bool = Field(default=True, description="是否启用")


class RoleUpdate(BaseModel):
    """更新角色请求"""

    name: str | None = Field(None, min_length=1, max_length=100, description="角色名称")
    description: str | None = Field(None, max_length=200, description="角色描述")
    scope: str | None = Field(None, description="作用域")
    is_active: bool | None = Field(None, description="是否启用")


class RoleResponse(BaseModel):
    """角色响应"""

    id: uuid.UUID
    name: str
    code: str
    description: str | None
    scope: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── 人员 Schema ──

class PersonnelAddRequest(BaseModel):
    """添加人员请求 — 从 identity.users 选取"""

    user_ids: list[uuid.UUID] = Field(
        ..., min_length=1, description="identity.users 的 ID 列表"
    )


class PersonnelAddResult(BaseModel):
    """添加人员结果"""

    added: list[uuid.UUID]
    skipped: list[uuid.UUID] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class PersonnelUpdate(BaseModel):
    """更新人员请求"""

    is_active: bool | None = Field(None, description="是否在岗")
    extended_attrs: dict | None = Field(None, description="扩展属性")


class PersonnelRoleAssign(BaseModel):
    """人员角色分配请求"""

    role_ids: list[uuid.UUID] = Field(..., description="角色 ID 列表")


class PersonnelCategoryItem(BaseModel):
    """单条分类绑定"""

    role_id: uuid.UUID
    category_id: uuid.UUID


class PersonnelCategoryAssign(BaseModel):
    """人员+角色绑定设备分类请求"""

    categories: list[PersonnelCategoryItem] = Field(
        default_factory=list, description="分类绑定列表"
    )


class PersonnelRoleInfo(BaseModel):
    """人员关联的角色信息"""

    id: uuid.UUID
    name: str
    code: str
    scope: str

    model_config = {"from_attributes": True}


class PersonnelCategoryInfo(BaseModel):
    """人员+角色→分类绑定信息"""

    role_id: uuid.UUID
    role_name: str
    category_id: uuid.UUID
    category_name: str


class PersonnelResponse(BaseModel):
    """人员响应"""

    id: uuid.UUID
    user_id: uuid.UUID | None
    name: str
    employee_no: str | None
    department: str | None
    position: str | None = None
    avatar_url: str | None = None
    feishu_user_id: str | None
    feishu_open_id: str | None
    mobile: str | None
    extended_attrs: dict | None
    is_active: bool
    roles: list[PersonnelRoleInfo] = Field(default_factory=list)
    categories: list[PersonnelCategoryInfo] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonnelListResponse(BaseModel):
    """人员列表响应"""

    items: list[PersonnelResponse]
    total: int
    page: int
    page_size: int


# ── 候选人查询 Schema ──

class CandidateResponse(BaseModel):
    """可分配人员信息（供其他业务模块调用）"""

    personnel_id: uuid.UUID
    name: str
    department: str | None
    feishu_user_id: str | None
    feishu_open_id: str | None
    roles: list[PersonnelRoleInfo] = Field(default_factory=list)


# ── 飞书刷新结果 ──

class FeishuRefreshResult(BaseModel):
    """飞书刷新结果"""

    total: int = Field(description="人员总数")
    updated: int = Field(description="成功更新数")
    skipped: int = Field(description="跳过（无变更）")
    unmatched: int = Field(description="未匹配（identity 中找不到）")
    errors: list[dict] = Field(default_factory=list)
