"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OhHealthExamBase(BaseModel):
    """职业健康体检基础字段"""

    exam_no: str = Field(..., max_length=64, description="体检编号")
    employee_name: str = Field(..., max_length=100, description="员工姓名")
    employee_id: str | None = Field(None, max_length=64, description="工号")
    department: str | None = Field(None, max_length=100, description="部门")
    job_position: str | None = Field(None, max_length=100, description="岗位")
    exam_type: str = Field(..., description="体检类型")
    exam_agency: str | None = Field(None, max_length=255, description="体检机构")
    scheduled_date: datetime | None = Field(None, description="计划体检日期")
    exam_date: datetime | None = Field(None, description="实际体检日期")
    report_date: datetime | None = Field(None, description="报告日期")
    hazard_factors: list | None = Field(None, description="关联的危害因素列表")
    overall_conclusion: str | None = Field(None, description="综合体检结论")
    exam_items: list | None = Field(None, description="体检项目结果")
    abnormality_records: list | None = Field(None, description="异常处置记录")
    attachments: list | None = Field(None, description="附件列表")
    notes: str | None = Field(None, description="备注")


class OhHealthExamCreate(OhHealthExamBase):
    """创建职业健康体检"""

    pass


class OhHealthExamUpdate(BaseModel):
    """更新职业健康体检（所有字段可选）"""

    exam_no: str | None = Field(None, max_length=64, description="体检编号")
    employee_name: str | None = Field(None, max_length=100, description="员工姓名")
    employee_id: str | None = Field(None, max_length=64, description="工号")
    department: str | None = Field(None, max_length=100, description="部门")
    job_position: str | None = Field(None, max_length=100, description="岗位")
    exam_type: str | None = Field(None, description="体检类型")
    exam_agency: str | None = Field(None, max_length=255, description="体检机构")
    scheduled_date: datetime | None = Field(None, description="计划体检日期")
    exam_date: datetime | None = Field(None, description="实际体检日期")
    report_date: datetime | None = Field(None, description="报告日期")
    hazard_factors: list | None = Field(None, description="关联的危害因素列表")
    overall_conclusion: str | None = Field(None, description="综合体检结论")
    exam_items: list | None = Field(None, description="体检项目结果")
    abnormality_records: list | None = Field(None, description="异常处置记录")
    attachments: list | None = Field(None, description="附件列表")
    notes: str | None = Field(None, description="备注")


class OhHealthExamResponse(OhHealthExamBase):
    """职业健康体检响应"""

    id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── 工作流请求 Schema ──


class SetExamConclusionRequest(BaseModel):
    """设置体检结论请求"""

    conclusion: str = Field(..., description="体检结论")
    remarks: str | None = Field(None, description="备注")


