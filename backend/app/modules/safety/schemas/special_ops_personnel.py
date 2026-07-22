"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    OperationType,
    PersonnelStatus,
)


class SpecialOperationPersonnelBase(BaseModel):
    """特殊作业人员资质基础模式"""

    personnel_no: str = Field(..., max_length=64, description="人员编号")
    name: str = Field(..., max_length=100, description="姓名")
    department: str | None = Field(None, max_length=100, description="所属部门")
    certificate_type: OperationType = Field(..., description="证书类型")
    certificate_number: str | None = Field(None, max_length=100, description="证书编号")
    issuing_authority: str | None = Field(None, max_length=200, description="发证机关")
    issue_date: datetime | None = Field(None, description="发证日期")
    expiry_date: datetime | None = Field(None, description="有效期至")
    certificate_file_path: str | None = Field(None, max_length=500, description="证书文件路径")
    qualification_scope: str | None = Field(None, description="资质范围")
    notes: str | None = Field(None, description="备注")


class SpecialOperationPersonnelCreate(SpecialOperationPersonnelBase):
    """创建人员资质"""
    pass


class SpecialOperationPersonnelUpdate(BaseModel):
    """更新人员资质"""

    personnel_no: str | None = Field(None, max_length=64, description="人员编号")
    name: str | None = Field(None, max_length=100, description="姓名")
    department: str | None = Field(None, max_length=100, description="所属部门")
    certificate_type: OperationType | None = Field(None, description="证书类型")
    certificate_number: str | None = Field(None, max_length=100, description="证书编号")
    issuing_authority: str | None = Field(None, max_length=200, description="发证机关")
    issue_date: datetime | None = Field(None, description="发证日期")
    expiry_date: datetime | None = Field(None, description="有效期至")
    certificate_file_path: str | None = Field(None, max_length=500, description="证书文件路径")
    qualification_scope: str | None = Field(None, description="资质范围")
    status: PersonnelStatus | None = Field(None, description="状态")
    notes: str | None = Field(None, description="备注")


class SpecialOperationPersonnelResponse(SpecialOperationPersonnelBase):
    """人员资质响应"""

    id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


