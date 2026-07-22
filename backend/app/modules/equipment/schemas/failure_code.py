"""Failure code schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ==================== 故障代码 ====================
FailureCodeType = Literal["symptom", "cause", "action"]


class FailureCodeCreate(BaseModel):
    """创建故障代码请求"""

    code: str = Field(..., min_length=1, max_length=50, description="代码")
    name: str = Field(..., min_length=1, max_length=100, description="名称")
    description: str | None = Field(default=None, description="描述")
    sort_order: int = Field(default=0, ge=0, description="排序")
    is_active: bool = Field(default=True, description="是否启用")


class FailureCodeUpdate(BaseModel):
    """更新故障代码请求"""

    code: str | None = Field(
        default=None, min_length=1, max_length=50, description="代码"
    )
    name: str | None = Field(
        default=None, min_length=1, max_length=100, description="名称"
    )
    description: str | None = Field(default=None, description="描述")
    sort_order: int | None = Field(default=None, ge=0, description="排序")
    is_active: bool | None = Field(default=None, description="是否启用")


class FailureCodeResponse(BaseModel):
    """故障代码响应"""

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}
