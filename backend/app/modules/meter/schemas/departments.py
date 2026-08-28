"""部门管理 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.meter.schemas.common import StrUUID


class DepartmentCreate(BaseModel):
    """新增部门。"""
    source: str = Field(..., pattern="^(instrument|gas_detector)$", description="来源: instrument / gas_detector")
    name: str = Field(..., min_length=1, max_length=200, description="部门名称")
    heads: list[dict[str, str]] = Field(
        default_factory=list,
        description="负责人列表 [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]",
    )





class DepartmentUpdate(BaseModel):
    """更新部门名称（改名联动更新对应表）。"""
    name: str = Field(..., min_length=1, max_length=200, description="新部门名称")
    heads: list[dict[str, str]] | None = Field(
        default=None,
        description="负责人列表 [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]",
    )
    auto_notify_enabled: bool | None = Field(default=None, description="部门级自动提醒开关")





class DepartmentResponse(BaseModel):
    """部门响应。"""
    id: StrUUID
    source: str
    name: str
    heads: list[dict[str, str]] = Field(default_factory=list, description="负责人列表")
    auto_notify_enabled: bool = False
    record_count: int = Field(default=0, description="关联记录数")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)





class PersonnelCandidate(BaseModel):
    """负责人候选人（从 identity.users 查询，前端下拉列表用）。"""
    name: str
    feishu_open_id: str
    department: str | None = None


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════
