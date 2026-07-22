"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── JSON 子记录 Schema ──


class RiskAssessmentItem(BaseModel):
    """风险评估记录"""

    method: str | None = Field(None, description="评估方法（LEC/LS/JHA/HAZOP等）")
    severity: str | None = Field(None, description="严重性")
    likelihood: str | None = Field(None, description="可能性")
    risk_level: str | None = Field(None, description="风险等级")
    description: str | None = Field(None, description="风险描述")
    control_measures: str | None = Field(None, description="控制措施")
    assessed_by: str | None = Field(None, max_length=100, description="评估人")
    assessed_date: str | None = Field(None, description="评估日期")
    participants: str | None = Field(None, description="参与人员")


class ApprovalChainItem(BaseModel):
    """审批链记录"""

    level: int = Field(..., description="审批层级")
    approver_role: str = Field(..., max_length=100, description="审批角色")
    approver: str | None = Field(None, max_length=100, description="审批人")
    decision: str = Field("pending", description="审批决定: pending/approved/rejected")
    comments: str | None = Field(None, description="审批意见")
    decided_at: str | None = Field(None, description="审批时间")


class ActionItem(BaseModel):
    """行动项"""

    task: str = Field(..., description="任务描述")
    owner: str | None = Field(None, max_length=100, description="责任人")
    due_date: str | None = Field(None, description="截止日期")
    status: str = Field("pending", description="状态: pending/in_progress/completed")
    completed_at: str | None = Field(None, description="完成时间")


class PSSRChecklistItem(BaseModel):
    """PSSR检查项"""

    item: str = Field(..., description="检查项")
    result: str = Field("na", description="结果: pass/fail/na")
    checked_by: str | None = Field(None, max_length=100, description="检查人")
    checked_at: str | None = Field(None, description="检查时间")
    remarks: str | None = Field(None, description="备注")


class VerificationDataSchema(BaseModel):
    """变更验证数据"""

    expected_effect_achieved: bool | None = Field(None, description="预期效果是否达成")
    comments: str | None = Field(None, description="验证意见")
    psi_updated: bool | None = Field(None, description="工艺安全信息是否已更新")
    documents_updated: bool | None = Field(None, description="相关文件是否已更新")
    accepted_by: str | None = Field(None, max_length=100, description="验收人")
    accepted_date: str | None = Field(None, description="验收日期")


class ClosureDataSchema(BaseModel):
    """变更关闭数据"""

    closed_by: str | None = Field(None, max_length=100, description="关闭人")
    closed_date: str | None = Field(None, description="关闭日期")
    temp_expiry_date: str | None = Field(None, description="临时变更到期日期")
    restored_date: str | None = Field(None, description="恢复原状日期")


# ── 主 Schema ──


class EhsChangeBase(BaseModel):
    """EHS变更基础字段"""

    change_no: str = Field(..., max_length=64, description="变更编号")
    title: str = Field(..., max_length=255, description="变更标题")
    change_type: str = Field(..., description="变更类型")
    change_grade: str = Field("general", description="变更等级")
    change_duration: str = Field("permanent", description="变更期限")
    department: str | None = Field(None, max_length=100, description="申请部门")
    location_unit: str | None = Field(None, max_length=255, description="所在单元/装置")
    description: str | None = Field(None, description="变更描述（变更前/变更后对比）")
    technical_basis: str | None = Field(None, description="变更技术依据")
    expected_start: datetime | None = Field(None, description="预期开始日期")
    expected_completion: datetime | None = Field(None, description="预期完成日期")
    actual_start: datetime | None = Field(None, description="实际开始日期")
    actual_completion: datetime | None = Field(None, description="实际完成日期")
    expected_effect: str | None = Field(None, description="预期效果")
    applicant_name: str | None = Field(None, max_length=100, description="申请人姓名")
    equipment_tags: list[str] | None = Field(None, description="关联设备位号")
    documents_to_update: list | None = Field(None, description="需更新的文件清单")
    attachments: list | None = Field(None, description="附件列表")
    risk_assessments: list | None = Field(None, description="风险评估记录")
    approval_chain: list | None = Field(None, description="审批链")
    action_items: list | None = Field(None, description="行动项")
    pssr_checklist: list | None = Field(None, description="PSSR检查清单")
    verification: dict | None = Field(None, description="变更验证数据")
    closure: dict | None = Field(None, description="变更关闭数据")
    linked_safety_check_id: uuid.UUID | None = Field(None, description="关联安全检查ID")
    notes: str | None = Field(None, description="备注")


class EhsChangeCreate(EhsChangeBase):
    """创建EHS变更"""

    pass


class EhsChangeUpdate(BaseModel):
    """更新EHS变更（所有字段可选）"""

    change_no: str | None = Field(None, max_length=64, description="变更编号")
    title: str | None = Field(None, max_length=255, description="变更标题")
    change_type: str | None = Field(None, description="变更类型")
    change_grade: str | None = Field(None, description="变更等级")
    change_duration: str | None = Field(None, description="变更期限")
    department: str | None = Field(None, max_length=100, description="申请部门")
    location_unit: str | None = Field(None, max_length=255, description="所在单元/装置")
    description: str | None = Field(None, description="变更描述")
    technical_basis: str | None = Field(None, description="变更技术依据")
    expected_start: datetime | None = Field(None, description="预期开始日期")
    expected_completion: datetime | None = Field(None, description="预期完成日期")
    actual_start: datetime | None = Field(None, description="实际开始日期")
    actual_completion: datetime | None = Field(None, description="实际完成日期")
    expected_effect: str | None = Field(None, description="预期效果")
    applicant_name: str | None = Field(None, max_length=100, description="申请人姓名")
    equipment_tags: list[str] | None = Field(None, description="关联设备位号")
    documents_to_update: list | None = Field(None, description="需更新的文件清单")
    attachments: list | None = Field(None, description="附件列表")
    risk_assessments: list | None = Field(None, description="风险评估记录")
    approval_chain: list | None = Field(None, description="审批链")
    action_items: list | None = Field(None, description="行动项")
    pssr_checklist: list | None = Field(None, description="PSSR检查清单")
    verification: dict | None = Field(None, description="变更验证数据")
    closure: dict | None = Field(None, description="变更关闭数据")
    linked_safety_check_id: uuid.UUID | None = Field(None, description="关联安全检查ID")
    notes: str | None = Field(None, description="备注")


class EhsChangeResponse(EhsChangeBase):
    """EHS变更响应"""

    id: uuid.UUID
    applicant_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── 工作流请求 Schema ──


class ApproveEhsChangeRequest(BaseModel):
    """审批EHS变更请求"""

    decision: str = Field(..., description="审批决定: approved/rejected")
    comments: str | None = Field(None, description="审批意见")


class CloseEhsChangeRequest(BaseModel):
    """关闭EHS变更请求"""

    closed_by: str | None = Field(None, max_length=100, description="关闭人")
    temp_expiry_date: str | None = Field(None, description="临时变更到期日期")
    restored_date: str | None = Field(None, description="恢复原状日期")


class AddRiskAssessmentRequest(BaseModel):
    """添加风险评估请求"""

    method: str | None = Field(None, description="评估方法")
    severity: str | None = Field(None, description="严重性")
    likelihood: str | None = Field(None, description="可能性")
    risk_level: str | None = Field(None, description="风险等级")
    description: str | None = Field(None, description="风险描述")
    control_measures: str | None = Field(None, description="控制措施")
    assessed_by: str | None = Field(None, max_length=100, description="评估人")
    assessed_date: str | None = Field(None, description="评估日期")
    participants: str | None = Field(None, description="参与人员")


class UpdateActionItemRequest(BaseModel):
    """更新行动项请求"""

    index: int = Field(..., ge=0, description="行动项索引")
    status: str = Field(..., description="状态: pending/in_progress/completed")


class SubmitVerificationRequest(BaseModel):
    """提交验证数据请求"""

    expected_effect_achieved: bool | None = Field(None, description="预期效果是否达成")
    comments: str | None = Field(None, description="验证意见")
    psi_updated: bool | None = Field(None, description="工艺安全信息是否已更新")
    documents_updated: bool | None = Field(None, description="相关文件是否已更新")
    accepted_by: str | None = Field(None, max_length=100, description="验收人")


# ==================== JSON 子记录 Schema ====================


class DetectionResultItem(BaseModel):
    """检测结果记录"""

    factor_name: str = Field(..., description="危害因素名称")
    factor_category: str = Field(..., description="危害因素类别: dust/chemical/physical")
    detection_value: float = Field(..., description="检测值")
    unit: str | None = Field(None, description="单位（mg/m³, dB(A), °C 等）")
    oel_limit: float | None = Field(None, description="职业接触限值（OEL）")
    compliance_status: str | None = Field(None, description="合规状态: compliant/exceeding/marginal")
    sampling_method: str | None = Field(None, description="采样方法")
    standard_ref: str | None = Field(None, description="标准参考")


class ExamResultItem(BaseModel):
    """体检项目结果"""

    item_name: str = Field(..., description="检查项目名称")
    category: str | None = Field(None, description="项目类别")
    result: str | None = Field(None, description="检查结果")
    reference_range: str | None = Field(None, description="参考范围")
    is_abnormal: bool | None = Field(None, description="是否异常")
    remarks: str | None = Field(None, description="备注")


class AbnormalityRecordItem(BaseModel):
    """异常处置记录"""

    abnormality_desc: str = Field(..., description="异常描述")
    corrective_action: str | None = Field(None, description="纠正措施")
    responsible_person: str | None = Field(None, max_length=100, description="责任人")
    deadline: str | None = Field(None, description="截止日期")
    status: str = Field("open", description="状态: open/investigating/corrected/closed")
    completed_at: str | None = Field(None, description="完成时间")
    remarks: str | None = Field(None, description="备注")


