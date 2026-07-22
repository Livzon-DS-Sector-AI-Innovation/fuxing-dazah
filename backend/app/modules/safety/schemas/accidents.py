"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    AccidentLevel,
    AccidentType,
)


class AccidentBase(BaseModel):
    """事故基础模式"""

    accident_no: str = Field(..., max_length=64, description="事故编号")
    accident_type: AccidentType = Field(..., description="事故类型")
    accident_level: AccidentLevel = Field(AccidentLevel.GENERAL, description="事故等级")
    happened_at: datetime = Field(..., description="发生时间")
    location: str | None = Field(None, max_length=255, description="发生地点")
    department: str | None = Field(None, max_length=100, description="发生部门")
    description: str = Field(..., description="事故描述")
    casualties: str | None = Field(None, max_length=255, description="伤亡情况汇总")
    property_damage: float | None = Field(None, ge=0, description="财产损失(元)")
    loss_work_days: int | None = Field(None, ge=0, description="损失工作日")
    injury_details: list | None = Field(None, description="伤员详情")
    investigation_team: list | None = Field(None, description="调查组")
    investigation_method: str | None = Field(None, max_length=100, description="调查方法")
    investigation_findings: str | None = Field(None, description="调查发现")
    investigation_report_path: str | None = Field(None, max_length=500, description="调查报告文件路径")
    direct_cause: str | None = Field(None, description="直接原因")
    root_cause: str | None = Field(None, description="根本原因")
    handling_measures: str | None = Field(None, description="处理措施")
    corrective_actions: str | None = Field(None, description="纠正预防措施")
    corrective_action_deadline: datetime | None = Field(None, description="CAPA截止日期")
    corrective_action_responsible: str | None = Field(None, max_length=100, description="CAPA责任人")
    corrective_action_status: str | None = Field(None, max_length=32, description="CAPA状态")
    reported_by: uuid.UUID | None = Field(None, description="报告人")
    reported_by_name: str | None = Field(None, max_length=100, description="报告人姓名")
    reported_at: datetime = Field(..., description="报告时间")
    notes: str | None = Field(None, description="备注")


class AccidentCreate(AccidentBase):
    """创建事故"""

    pass


class AccidentUpdate(BaseModel):
    """更新事故"""

    accident_no: str | None = Field(None, max_length=64, description="事故编号")
    accident_type: AccidentType | None = Field(None, description="事故类型")
    accident_level: AccidentLevel | None = Field(None, description="事故等级")
    happened_at: datetime | None = Field(None, description="发生时间")
    location: str | None = Field(None, max_length=255, description="发生地点")
    department: str | None = Field(None, max_length=100, description="发生部门")
    description: str | None = Field(None, description="事故描述")
    casualties: str | None = Field(None, max_length=255, description="伤亡情况汇总")
    property_damage: float | None = Field(None, ge=0, description="财产损失(元)")
    loss_work_days: int | None = Field(None, ge=0, description="损失工作日")
    injury_details: list | None = Field(None, description="伤员详情")
    investigation_team: list | None = Field(None, description="调查组")
    investigation_method: str | None = Field(None, max_length=100, description="调查方法")
    investigation_findings: str | None = Field(None, description="调查发现")
    investigation_report_path: str | None = Field(None, max_length=500, description="调查报告文件路径")
    direct_cause: str | None = Field(None, description="直接原因")
    root_cause: str | None = Field(None, description="根本原因")
    handling_measures: str | None = Field(None, description="处理措施")
    corrective_actions: str | None = Field(None, description="纠正预防措施")
    corrective_action_deadline: datetime | None = Field(None, description="CAPA截止日期")
    corrective_action_responsible: str | None = Field(None, max_length=100, description="CAPA责任人")
    corrective_action_status: str | None = Field(None, max_length=32, description="CAPA状态")
    status: str | None = Field(None, max_length=32, description="状态")
    investigator: uuid.UUID | None = Field(None, description="调查人")
    investigator_name: str | None = Field(None, max_length=100, description="调查人姓名")
    verified_by: uuid.UUID | None = Field(None, description="CAPA验证人")
    verified_by_name: str | None = Field(None, max_length=100, description="验证人姓名")
    verified_at: datetime | None = Field(None, description="验证时间")
    notes: str | None = Field(None, description="备注")


class AccidentResponse(AccidentBase):
    """事故响应"""

    id: uuid.UUID
    status: str
    investigator: uuid.UUID | None = None
    investigator_name: str | None = None
    verified_by: uuid.UUID | None = None
    verified_by_name: str | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


