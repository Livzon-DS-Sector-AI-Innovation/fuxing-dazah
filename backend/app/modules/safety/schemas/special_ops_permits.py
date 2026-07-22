"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    CompletionMethod,
    OperationLevel,
    OperationType,
    PermitStatus,
)


class SpecialOperationPermitBase(BaseModel):
    """特殊作业票基础模式"""

    permit_no: str = Field(..., max_length=64, description="作业票编号")
    operation_type: OperationType = Field(..., description="作业类型")
    operation_level: OperationLevel = Field(OperationLevel.GRADE2, description="作业级别")
    location: str | None = Field(None, max_length=255, description="作业地点")
    equipment_tag: str | None = Field(None, max_length=100, description="设备位号")
    work_description: str | None = Field(None, description="作业内容描述")
    planned_start_time: datetime | None = Field(None, description="计划开始时间")
    planned_end_time: datetime | None = Field(None, description="计划结束时间")
    actual_start_time: datetime | None = Field(None, description="实际开始时间")
    actual_end_time: datetime | None = Field(None, description="实际结束时间")
    applicant_name: str | None = Field(None, max_length=100, description="申请人姓名")
    work_leader_name: str | None = Field(None, max_length=100, description="作业负责人姓名")
    operator_names: str | None = Field(None, description="作业人员姓名")
    guardian_name: str | None = Field(None, max_length=100, description="监护人姓名")
    approver_name: str | None = Field(None, max_length=100, description="审批人姓名")
    safety_measures: str | None = Field(None, description="安全措施")
    emergency_equipment: str | None = Field(None, description="应急消防器材")
    gas_analysis: str | None = Field(None, description="气体分析结果")
    risk_assessment: str | None = Field(None, description="风险评估")
    check_id: uuid.UUID | None = Field(None, description="关联安全检查ID")
    notes: str | None = Field(None, description="备注")


class SpecialOperationPermitCreate(SpecialOperationPermitBase):
    """创建作业票"""
    pass


class SpecialOperationPermitUpdate(BaseModel):
    """更新作业票"""

    permit_no: str | None = Field(None, max_length=64, description="作业票编号")
    operation_type: OperationType | None = Field(None, description="作业类型")
    operation_level: OperationLevel | None = Field(None, description="作业级别")
    location: str | None = Field(None, max_length=255, description="作业地点")
    equipment_tag: str | None = Field(None, max_length=100, description="设备位号")
    work_description: str | None = Field(None, description="作业内容描述")
    planned_start_time: datetime | None = Field(None, description="计划开始时间")
    planned_end_time: datetime | None = Field(None, description="计划结束时间")
    actual_start_time: datetime | None = Field(None, description="实际开始时间")
    actual_end_time: datetime | None = Field(None, description="实际结束时间")
    applicant_name: str | None = Field(None, max_length=100, description="申请人姓名")
    work_leader_name: str | None = Field(None, max_length=100, description="作业负责人姓名")
    operator_names: str | None = Field(None, description="作业人员姓名")
    guardian_name: str | None = Field(None, max_length=100, description="监护人姓名")
    approver_name: str | None = Field(None, max_length=100, description="审批人姓名")
    safety_measures: str | None = Field(None, description="安全措施")
    emergency_equipment: str | None = Field(None, description="应急消防器材")
    gas_analysis: str | None = Field(None, description="气体分析结果")
    risk_assessment: str | None = Field(None, description="风险评估")
    safety_briefing_confirmed: bool | None = Field(None, description="安全交底确认")
    safety_briefing_time: datetime | None = Field(None, description="安全交底时间")
    rejection_reason: str | None = Field(None, description="驳回原因")
    completion_method: CompletionMethod | None = Field(None, description="完工方式")
    status: PermitStatus | None = Field(None, description="状态")
    check_id: uuid.UUID | None = Field(None, description="关联安全检查ID")
    notes: str | None = Field(None, description="备注")


class SpecialOperationPermitResponse(SpecialOperationPermitBase):
    """作业票响应"""

    id: uuid.UUID
    safety_briefing_confirmed: bool = False
    safety_briefing_time: datetime | None = None
    rejection_reason: str | None = None
    completion_method: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


