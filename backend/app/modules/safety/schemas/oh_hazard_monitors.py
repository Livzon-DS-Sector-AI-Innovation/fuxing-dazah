"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OhHazardMonitorBase(BaseModel):
    """职业危害因素监测基础字段"""

    monitor_no: str = Field(..., max_length=64, description="监测编号")
    workplace: str = Field(..., max_length=255, description="监测场所/车间")
    location: str | None = Field(None, max_length=255, description="具体监测点位")
    equipment_info: str | None = Field(None, max_length=255, description="关联设备/岗位")
    detection_type: str = Field(..., description="检测类型")
    detection_date: datetime | None = Field(None, description="检测日期")
    detection_agency: str | None = Field(None, max_length=255, description="检测机构")
    inspector_name: str | None = Field(None, max_length=100, description="检测人员")
    verifier_name: str | None = Field(None, max_length=100, description="验证人员")
    detection_results: list | None = Field(None, description="检测结果数组")
    abnormality_records: list | None = Field(None, description="异常处置记录")
    attachments: list | None = Field(None, description="附件列表")
    notes: str | None = Field(None, description="备注")


class OhHazardMonitorCreate(OhHazardMonitorBase):
    """创建危害因素监测"""

    pass


class OhHazardMonitorUpdate(BaseModel):
    """更新危害因素监测（所有字段可选）"""

    monitor_no: str | None = Field(None, max_length=64, description="监测编号")
    workplace: str | None = Field(None, max_length=255, description="监测场所/车间")
    location: str | None = Field(None, max_length=255, description="具体监测点位")
    equipment_info: str | None = Field(None, max_length=255, description="关联设备/岗位")
    detection_type: str | None = Field(None, description="检测类型")
    detection_date: datetime | None = Field(None, description="检测日期")
    detection_agency: str | None = Field(None, max_length=255, description="检测机构")
    inspector_name: str | None = Field(None, max_length=100, description="检测人员")
    verifier_name: str | None = Field(None, max_length=100, description="验证人员")
    detection_results: list | None = Field(None, description="检测结果数组")
    abnormality_records: list | None = Field(None, description="异常处置记录")
    attachments: list | None = Field(None, description="附件列表")
    notes: str | None = Field(None, description="备注")


class OhHazardMonitorResponse(OhHazardMonitorBase):
    """危害因素监测响应"""

    id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── 工作流请求 Schema ──


class VerifyMonitorRequest(BaseModel):
    """验证监测请求"""

    verified_by: str | None = Field(None, max_length=100, description="验证人")
    comments: str | None = Field(None, description="验证意见")


