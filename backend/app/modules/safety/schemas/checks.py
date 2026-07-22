"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    CheckType,
)


class SafetyCheckBase(BaseModel):
    """安全检查基础模式"""

    check_no: str = Field(..., max_length=64, description="检查编号")
    check_type: CheckType = Field(CheckType.DAILY, description="检查类型")
    check_date: datetime = Field(..., description="检查日期")
    department: str | None = Field(None, max_length=100, description="检查部门")
    inspector: uuid.UUID | None = Field(None, description="检查人")
    inspector_name: str | None = Field(None, max_length=100, description="检查人姓名")
    location: str | None = Field(None, max_length=255, description="检查地点")
    findings: str | None = Field(None, description="检查发现")
    result: str | None = Field(None, max_length=32, description="检查结果")
    rectification_required: bool = Field(False, description="是否需要整改")
    rectification_deadline: datetime | None = Field(None, description="整改期限")
    inspector_confirmed: bool = Field(False, description="检查人员确认")
    safety_officer_confirmed: bool = Field(False, description="安全办确认")
    notes: str | None = Field(None, description="备注")


class SafetyCheckCreate(SafetyCheckBase):
    """创建安全检查"""

    pass


class SafetyCheckUpdate(BaseModel):
    """更新安全检查"""

    check_no: str | None = Field(None, max_length=64, description="检查编号")
    check_type: CheckType | None = Field(None, description="检查类型")
    check_date: datetime | None = Field(None, description="检查日期")
    department: str | None = Field(None, max_length=100, description="检查部门")
    inspector: uuid.UUID | None = Field(None, description="检查人")
    inspector_name: str | None = Field(None, max_length=100, description="检查人姓名")
    location: str | None = Field(None, max_length=255, description="检查地点")
    findings: str | None = Field(None, description="检查发现")
    result: str | None = Field(None, max_length=32, description="检查结果")
    rectification_required: bool | None = Field(None, description="是否需要整改")
    rectification_deadline: datetime | None = Field(None, description="整改期限")
    rectification_status: str | None = Field(None, max_length=32, description="整改进度")
    inspector_confirmed: bool | None = Field(None, description="检查人员确认")
    safety_officer_confirmed: bool | None = Field(None, description="安全办确认")
    status: str | None = Field(None, max_length=32, description="状态")
    notes: str | None = Field(None, description="备注")


class SafetyCheckResponse(SafetyCheckBase):
    """安全检查响应"""

    id: uuid.UUID
    rectification_status: str | None = None
    inspector_confirmed: bool = False
    safety_officer_confirmed: bool = False
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


