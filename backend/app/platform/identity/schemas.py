import datetime
import json
from uuid import UUID

from pydantic import BaseModel, field_validator


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"


class SSOCallbackResult(BaseModel):
    token: str
    redirect_url: str


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    mobile: str | None = None
    avatar_url: str | None = None
    employee_no: str | None = None
    department: str | None = None
    position: str | None = None
    feishu_user_id: str | None = None

    model_config = {"from_attributes": True}


# ── Department ──────────────────────────────────────────────────────


class DepartmentResponse(BaseModel):
    id: UUID
    feishu_department_id: str
    name: str
    parent_feishu_department_id: str | None = None
    leader_user_id: str | None = None
    member_count: int | None = None
    status_is_deleted: bool | None = None
    path: str | None = None
    order: int | None = None

    @field_validator("path", mode="before")
    @classmethod
    def path_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, list | dict):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    model_config = {"from_attributes": True}


class DepartmentTreeNode(BaseModel):
    """组织架构树节点（含子部门）"""
    id: UUID
    feishu_department_id: str
    name: str
    member_count: int | None = None
    leader_user_id: str | None = None
    order: int | None = None
    children: list["DepartmentTreeNode"] = []

    model_config = {"from_attributes": True}


# ── Personnel ───────────────────────────────────────────────────────


class PersonnelItem(BaseModel):
    """人员列表项"""
    id: UUID
    name: str
    employee_no: str | None = None
    email: str | None = None
    mobile: str | None = None
    department: str | None = None
    position: str | None = None
    feishu_user_id: str | None = None
    avatar_url: str | None = None
    feishu_department_ids: list[str] | None = None

    @field_validator("feishu_department_ids", mode="before")
    @classmethod
    def parse_dept_ids(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            try:
                result = json.loads(v)
                if isinstance(result, list):
                    return [str(x) for x in result]
                return None
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    model_config = {"from_attributes": True}


class PersonnelListResponse(BaseModel):
    """人员分页列表"""
    items: list[PersonnelItem]
    total: int
    offset: int
    limit: int


# ── Impersonation ─────────────────────────────────────────────────────


class ImpersonateStartRequest(BaseModel):
    target_user_id: UUID


class ImpersonateStartResponse(BaseModel):
    target_user_id: UUID
    target_user_name: str
    target_department: str
    target_position: str
    token: str  # Server Action 用来设置 cookie
    expires_at: datetime.datetime


class ImpersonateUserInfo(BaseModel):
    id: UUID
    name: str
    department: str
    position: str

    model_config = {"from_attributes": True}


class ImpersonateStatusResponse(BaseModel):
    is_impersonating: bool
    real_user: ImpersonateUserInfo | None = None
    target_user: ImpersonateUserInfo | None = None
    expires_at: datetime.datetime | None = None
