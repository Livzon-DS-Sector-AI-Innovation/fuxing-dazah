"""职业健康体检申请（转岗/离岗）schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.5 OhExamApplication 列定义。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OhTransferType(StrEnum):
    """转岗/离岗类型"""

    TRANSFER = "transfer"
    POST_EMPLOYMENT = "post_employment"


OH_TRANSFER_TYPE_OPTIONS = [
    {"value": OhTransferType.TRANSFER, "label": "转岗"},
    {"value": OhTransferType.POST_EMPLOYMENT, "label": "离岗"},
]


class OhApplicationStatus(StrEnum):
    """申请状态（Bitable 7 态原文值）"""

    APPROVED = "已通过"
    REVIEWING = "审批中"
    REJECTED = "已拒绝"
    CANCELLED = "已取消"
    TERMINATED = "已终止"
    WITHDRAWN = "已撤回"
    DELETED = "已删除"


OH_APPLICATION_STATUS_OPTIONS = [
    {"value": OhApplicationStatus.APPROVED, "label": "已通过", "color": "green"},
    {"value": OhApplicationStatus.REVIEWING, "label": "审批中", "color": "processing"},
    {"value": OhApplicationStatus.REJECTED, "label": "已拒绝", "color": "red"},
    {"value": OhApplicationStatus.CANCELLED, "label": "已取消", "color": "default"},
    {"value": OhApplicationStatus.TERMINATED, "label": "已终止", "color": "default"},
    {"value": OhApplicationStatus.WITHDRAWN, "label": "已撤回", "color": "default"},
    {"value": OhApplicationStatus.DELETED, "label": "已删除", "color": "default"},
]


class OhDiffAnalyzeStatus(StrEnum):
    """差异分析状态"""

    NONE = "none"
    PARSING = "parsing"
    ANALYZED = "analyzed"
    FAILED = "failed"


class OhExamApplicationBase(BaseModel):
    """体检申请基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    application_no: str | None = Field(None, max_length=64, description="申请编号")
    apply_status: OhApplicationStatus | None = Field(None, description="申请状态")
    approval_flow: str | None = Field(None, max_length=100, description="审批流程名称")
    approval_node: str | None = Field(None, max_length=100, description="当前审批节点")
    current_handler: str | None = Field(None, max_length=100, description="当前处理人")
    initiator_name: str | None = Field(None, max_length=100, description="发起人姓名")
    submitted_at: datetime | None = Field(None, description="发起时间")
    completed_at: datetime | None = Field(None, description="完成时间")
    transfer_type: OhTransferType | None = Field(None, description="转岗/离岗")
    exam_type: str | None = Field(None, max_length=32, description="体检类型: 离岗体检/转岗体检")
    employee_name: str | None = Field(None, max_length=100, description="员工姓名")
    id_card_no: str | None = Field(None, max_length=32, description="身份证号")
    department: str | None = Field(None, max_length=100, description="原部门")
    position: str | None = Field(None, max_length=100, description="原岗位")
    new_department: str | None = Field(None, max_length=100, description="转入部门")
    new_position: str | None = Field(None, max_length=100, description="转入岗位")
    transfer_date: datetime | None = Field(None, description="转岗日期")
    leave_date: datetime | None = Field(None, description="离岗日期")
    dept_safety_officer: str | None = Field(None, max_length=100, description="部门安全员")
    applicant_name: str | None = Field(None, max_length=100, description="申请人")
    apply_date: datetime | None = Field(None, description="申请日期")
    diff_analyze_status: OhDiffAnalyzeStatus = Field(OhDiffAnalyzeStatus.NONE, description="差异分析状态")
    diff_analyze_error: str | None = Field(None, description="差异分析失败原因")
    diff_analyze_result: dict | None = Field(None, description="OhTransferDiffOutput 全量")
    diff_summary: str | None = Field(None, description="差异分析摘要")
    needs_exam: bool | None = Field(None, description="是否需体检（AI 输出）")
    exam_suggestion: str | None = Field(None, max_length=32, description="建议体检类型")
    created_exam_id: uuid.UUID | None = Field(None, description="自动创建的体检登记 oh_health_exams.id")
    bt_extra: dict | None = Field(None, description="Bitable 脏字段兜底")
    notes: str | None = Field(None, description="备注")


class OhExamApplicationCreate(OhExamApplicationBase):
    """创建体检申请"""

    pass


class OhExamApplicationUpdate(BaseModel):
    """更新体检申请（所有字段可选）"""

    model_config = ConfigDict(use_enum_values=True)

    application_no: str | None = Field(None, max_length=64)
    apply_status: OhApplicationStatus | None = None
    approval_flow: str | None = Field(None, max_length=100)
    approval_node: str | None = Field(None, max_length=100)
    current_handler: str | None = Field(None, max_length=100)
    initiator_name: str | None = Field(None, max_length=100)
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    transfer_type: OhTransferType | None = None
    exam_type: str | None = Field(None, max_length=32)
    employee_name: str | None = Field(None, max_length=100)
    id_card_no: str | None = Field(None, max_length=32)
    department: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    new_department: str | None = Field(None, max_length=100)
    new_position: str | None = Field(None, max_length=100)
    transfer_date: datetime | None = None
    leave_date: datetime | None = None
    dept_safety_officer: str | None = Field(None, max_length=100)
    applicant_name: str | None = Field(None, max_length=100)
    apply_date: datetime | None = None
    diff_analyze_error: str | None = None
    diff_analyze_result: dict | None = None
    diff_summary: str | None = None
    needs_exam: bool | None = None
    exam_suggestion: str | None = Field(None, max_length=32)
    created_exam_id: uuid.UUID | None = None
    bt_extra: dict | None = None
    notes: str | None = None


class OhExamApplicationResponse(OhExamApplicationBase):
    """体检申请响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
