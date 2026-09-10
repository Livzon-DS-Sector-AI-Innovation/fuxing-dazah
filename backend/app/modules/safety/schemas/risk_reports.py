"""Safety request and response schemas."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    OperationLevel,
    OperationType,
)


class ReportStatus(str, Enum):
    """报备状态枚举"""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


REPORT_STATUS_OPTIONS = [
    {"value": ReportStatus.DRAFT, "label": "草稿"},
    {"value": ReportStatus.SUBMITTED, "label": "已提交"},
    {"value": ReportStatus.APPROVED, "label": "已审批"},
    {"value": ReportStatus.REJECTED, "label": "已驳回"},
]


# ── 八大特殊作业报备 ──


class SpecialOperationReportBase(BaseModel):
    """特殊作业报备基础模式"""

    report_no: str = Field(..., max_length=64, description="报备编号")
    permit_id: uuid.UUID | None = Field(None, description="关联作业票ID")
    operation_type: OperationType = Field(..., description="作业类型")
    operation_level: OperationLevel = Field(OperationLevel.GRADE2, description="作业级别")
    department: str | None = Field(None, max_length=100, description="报备部门")
    location: str | None = Field(None, max_length=255, description="作业地点")
    equipment_tag: str | None = Field(None, max_length=100, description="设备位号")
    work_description: str | None = Field(None, description="作业内容描述")
    planned_start_time: datetime | None = Field(None, description="计划开始时间")
    planned_end_time: datetime | None = Field(None, description="计划结束时间")
    work_leader_name: str | None = Field(None, max_length=100, description="作业负责人姓名")
    operator_names: str | None = Field(None, description="作业人员姓名（逗号分隔）")
    guardian_name: str | None = Field(None, max_length=100, description="监护人姓名")
    risk_level: str | None = Field(None, max_length=20, description="风险等级")
    safety_measures: str | None = Field(None, description="安全措施")
    emergency_equipment: str | None = Field(None, description="应急消防器材")
    gas_analysis: str | None = Field(None, description="气体分析结果")
    risk_assessment: str | None = Field(None, description="风险评估描述")
    applicant_name: str | None = Field(None, max_length=100, description="报备申请人姓名")
    approver_name: str | None = Field(None, max_length=100, description="审批人姓名")
    notes: str | None = Field(None, description="备注")
    is_critical: bool = Field(False, description="是否关键作业")
    is_critical_reason: str | None = Field(None, description="关键作业判定理由")


class SpecialOperationReportCreate(SpecialOperationReportBase):
    """创建特殊作业报备"""
    pass


class SpecialOperationReportUpdate(BaseModel):
    """更新特殊作业报备"""

    report_no: str | None = Field(None, max_length=64, description="报备编号")
    permit_id: uuid.UUID | None = Field(None, description="关联作业票ID")
    operation_type: OperationType | None = Field(None, description="作业类型")
    operation_level: OperationLevel | None = Field(None, description="作业级别")
    department: str | None = Field(None, max_length=100, description="报备部门")
    location: str | None = Field(None, max_length=255, description="作业地点")
    equipment_tag: str | None = Field(None, max_length=100, description="设备位号")
    work_description: str | None = Field(None, description="作业内容描述")
    planned_start_time: datetime | None = Field(None, description="计划开始时间")
    planned_end_time: datetime | None = Field(None, description="计划结束时间")
    work_leader_name: str | None = Field(None, max_length=100, description="作业负责人姓名")
    operator_names: str | None = Field(None, description="作业人员姓名")
    guardian_name: str | None = Field(None, max_length=100, description="监护人姓名")
    risk_level: str | None = Field(None, max_length=20, description="风险等级")
    safety_measures: str | None = Field(None, description="安全措施")
    emergency_equipment: str | None = Field(None, description="应急消防器材")
    gas_analysis: str | None = Field(None, description="气体分析结果")
    risk_assessment: str | None = Field(None, description="风险评估描述")
    applicant_name: str | None = Field(None, max_length=100, description="报备申请人姓名")
    approver_name: str | None = Field(None, max_length=100, description="审批人姓名")
    status: ReportStatus | None = Field(None, description="状态")
    notes: str | None = Field(None, description="备注")
    is_critical: bool | None = Field(None, description="是否关键作业")
    is_critical_reason: str | None = Field(None, description="关键作业判定理由")
    # V3.5 风险判定字段（平台直输/同步）
    fire_work_method: str | None = Field(None, description="动火方式")
    height_work_method: str | None = Field(None, description="高处作业方式")
    work_height: float | None = Field(None, description="作业高度(米)")
    lifting_weight: float | None = Field(None, description="吊物质量(吨)")
    contractor_name: str | None = Field(None, description="施工单位")


class SpecialOperationReportResponse(SpecialOperationReportBase):
    """特殊作业报备响应"""

    id: uuid.UUID
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    status: str
    is_critical: bool = False
    is_critical_reason: str | None = None
    is_critical_updated_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # ── Bitable 同步 + 日报分析字段 ──
    source: str | None = None
    feishu_record_id: str | None = None
    personnel_type: str | None = None
    work_duration_hours: float | None = None
    is_weekend_holiday: str | None = None
    is_national_holiday: str | None = None
    holiday_period: str | None = None
    report_type: str | None = None
    initiator_department: str | None = None
    initiator_name: str | None = None
    approver_type: str | None = None
    safety_approver_name: str | None = None
    approval_no: str | None = None
    work_plan_url: str | None = None
    work_scheme_url: str | None = None
    approved_permit_url: str | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    approval_node: str | None = None
    daily_risk_level: str | None = None
    daily_risk_reason: str | None = None
    inferred_operation_types: list | None = None
    is_excluded: bool = False
    exclusion_reason: str | None = None
    # V3.5 风险判定字段
    fire_work_method: str | None = None
    height_work_method: str | None = None
    work_height: float | None = None
    lifting_weight: float | None = None
    contractor_name: str | None = None
    daily_report_date: datetime | None = None
    has_other_operations: str | None = None
    other_operation_types: list | None = None
    # V3.5 新增字段
    fire_work_method: str | None = None
    height_work_method: str | None = None
    work_height: float | None = None
    lifting_weight: float | None = None
    contractor_name: str | None = None

    class Config:
        from_attributes = True


class SpecialOperationLedgerStats(BaseModel):
    """特殊作业台账统计"""
    operation_type: str = Field(..., description="作业类型")
    count: int = Field(..., description="总数")
    critical_count: int = Field(0, description="关键作业数")


class SetCriticalRequest(BaseModel):
    """手动设置关键作业标记"""
    is_critical: bool = Field(..., description="是否关键作业")
    reason: str | None = Field(None, description="修改理由")


class LedgerExportRequest(BaseModel):
    """台账导出请求 — AI自然语言筛选"""
    natural_query: str | None = Field(None, description="自然语言筛选条件，例如「导出上月所有特级动火作业」")
    operation_type: str | None = Field(None, description="作业类型")
    operation_level: str | None = Field(None, description="作业级别")
    risk_level: str | None = Field(None, description="风险等级")
    department: str | None = Field(None, description="部门")
    date_from: str | None = Field(None, description="开始日期 YYYY-MM-DD")
    date_to: str | None = Field(None, description="结束日期 YYYY-MM-DD")
    keyword: str | None = Field(None, description="关键词搜索")
    is_critical: bool | None = Field(None, description="是否关键作业")


class LedgerExportParsedFilters(BaseModel):
    """AI 解析后的台账筛选条件"""
    operation_type: str | None = None
    operation_level: str | None = None
    risk_level: str | None = None
    department: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    keyword: str | None = None
    is_critical: bool | None = None
    explanation: str = Field("", description="AI 对筛选条件的解读说明")


# ── 危险源辨识台账导出 ──


class HazardLedgerExportRequest(BaseModel):
    """危险源辨识台账导出请求 — AI自然语言筛选 / 按 ids 精确导出"""
    natural_query: str | None = Field(None, description="自然语言筛选条件，例如「上月所有重大风险记录」")
    department: str | None = Field(None, description="部门")
    position: str | None = Field(None, description="岗位")
    risk_level: str | None = Field(None, description="风险等级: level_1/level_2/level_3/level_4")
    date_from: str | None = Field(None, description="创建时间起 YYYY-MM-DD")
    date_to: str | None = Field(None, description="创建时间止 YYYY-MM-DD")
    keyword: str | None = Field(None, description="关键词搜索（编号/部门/岗位/作业活动）")
    ids: list[str] | None = Field(
        None,
        max_length=500,
        description="危险源辨识记录 ID 列表，指定时按 ID 精确导出（忽略状态过滤）",
    )


class HazardLedgerExportParsedFilters(BaseModel):
    """AI 解析后的危险源辨识台账筛选条件"""
    department: str | None = None
    position: str | None = None
    risk_level: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    keyword: str | None = None
    explanation: str = Field("", description="AI 对筛选条件的解读说明")


