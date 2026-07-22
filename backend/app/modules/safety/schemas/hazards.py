"""Safety request and response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    HazardCategory,
    HazardLevel,
    HazardType,
)


class RectificationReplyRequest(BaseModel):
    """整改回复请求（合并了原 complete_rectification 步骤）"""

    reply_content: str = Field(..., description="整改回复内容")
    rectification_photos: str | None = Field(None, description="整改后图片JSON数组")
    corrective_preventive_measures: str | None = Field(None, description="AI整改建议（兼容旧字段）")
    rectification_reply: str | None = Field(None, description="整改回复内容（新字段）")
    actual_completion_date: datetime | None = Field(None, description="整改完成时间（默认当前时间）")


class VerifyLevelRequest(BaseModel):
    """三级复核请求"""

    level: int = Field(..., ge=1, le=3, description="复核级别: 1/2/3")
    action: str = Field(..., description="approved | rejected")
    opinion: str | None = Field(None, description="复核意见")


class ConfirmCheckRequest(BaseModel):
    """确认检查请求"""

    role: str = Field(..., description="确认角色: inspector / safety_officer")


class HazardStatsResponse(BaseModel):
    """隐患统计（全局，不受分页/筛选影响）"""

    total: int = 0
    pending_review: int = 0
    pending: int = 0
    in_progress: int = 0
    replied: int = 0
    verifying: int = 0
    rejected: int = 0
    closed: int = 0
    overdue: int = 0


class HazardReportBase(BaseModel):
    """隐患报告基础模式"""

    hazard_no: str = Field(..., max_length=64, description="隐患编号")
    inspection_category: str | None = Field(None, max_length=64, description="检查类别（日常检查/专项检查…）")
    hazard_type: HazardType = Field(..., description="隐患分类（人/物/环/管）")
    hazard_level: HazardLevel = Field(HazardLevel.GENERAL, description="隐患等级")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别（设备设施/危化储存…）")
    description: str = Field(..., description="隐患描述")
    discovered_by: uuid.UUID | None = Field(None, description="发现人")
    discovered_by_name: str | None = Field(None, max_length=100, description="检查人员姓名")
    inspector_department: str | None = Field(None, max_length=500, description="检查人员部门（Bitable 多选，逗号分隔）")
    discovered_at: datetime = Field(..., description="检查日期")
    department: str | None = Field(None, max_length=100, description="责任部门")
    major_hazard_basis: str | None = Field(None, description="隐患判定依据（AI）")
    key_defect: str | None = Field(None, description="隐患描述（AI）")
    defect_photos: str | None = Field(None, description="缺陷图片JSON数组")
    rectification_responsible_person: uuid.UUID | None = Field(None, description="整改责任人（FK → identity.users）")
    rectification_responsible_person_name: str | None = Field(None, max_length=100, description="整改责任人姓名")
    corrective_preventive_measures: str | None = Field(None, description="AI整改建议")
    rectification_reply: str | None = Field(None, description="整改回复内容")
    deadline: datetime | None = Field(None, description="整改期限")
    actual_completion_date: datetime | None = Field(None, description="整改完成时间")
    rectification_photos: str | None = Field(None, description="整改后图片JSON数组")
    check_id: uuid.UUID | None = Field(None, description="关联检查ID")
    notes: str | None = Field(None, description="备注")


class HazardReportCreate(HazardReportBase):
    """创建隐患报告"""

    hazard_no: str | None = Field(None, max_length=64, description="隐患编号（留空自动生成）")
    hazard_type: HazardType | None = Field(None, description="隐患分类")
    hazard_level: HazardLevel | None = Field(None, description="隐患等级")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别")
    description: str | None = Field(None, description="隐患描述")
    discovered_at: datetime | None = Field(None, description="发现时间")


class HazardReportUpdate(BaseModel):
    """更新隐患报告"""

    hazard_no: str | None = Field(None, max_length=64, description="隐患编号")
    inspection_category: str | None = Field(None, max_length=64, description="检查类别（日常检查/专项检查…）")
    hazard_type: HazardType | None = Field(None, description="隐患分类")
    hazard_level: HazardLevel | None = Field(None, description="隐患等级")
    hazard_category: HazardCategory | None = Field(None, description="隐患类别")
    description: str | None = Field(None, description="隐患描述")
    discovered_by: uuid.UUID | None = Field(None, description="发现人（FK → identity.users）")
    discovered_by_name: str | None = Field(None, max_length=100, description="检查人员姓名")
    discovered_at: datetime | None = Field(None, description="检查日期")
    department: str | None = Field(None, max_length=100, description="责任部门")
    inspector_department: str | None = Field(None, max_length=500, description="检查人员部门（Bitable 多选，逗号分隔）")
    major_hazard_basis: str | None = Field(None, description="隐患判定依据（AI）")
    key_defect: str | None = Field(None, description="隐患描述（AI）")
    defect_photos: str | None = Field(None, description="缺陷图片JSON数组")
    rectification_responsible_person: uuid.UUID | None = Field(None, description="整改责任人（FK → identity.users）")
    rectification_responsible_person_name: str | None = Field(None, max_length=100, description="整改责任人姓名")
    corrective_preventive_measures: str | None = Field(None, description="AI整改建议")
    rectification_reply: str | None = Field(None, description="整改回复内容")
    deadline: datetime | None = Field(None, description="整改期限")
    actual_completion_date: datetime | None = Field(None, description="整改完成时间")
    rectification_photos: str | None = Field(None, description="整改后图片JSON数组")
    rectification_status: str | None = Field(None, max_length=32, description="整改进度")
    status: str | None = Field(None, max_length=32, description="状态")
    notes: str | None = Field(None, description="备注")
    # ── AI 流程字段 ──
    ai_node_progress: str | None = Field(None, max_length=50, description="AI流程节点进度")
    overall_status: str | None = Field(None, max_length=20, description="整体状态")
    ai_error_message: str | None = Field(None, description="AI错误信息")
    script1_review_status: str | None = Field(None, max_length=20, description="AI隐患识别审核状态")
    script2_review_status: str | None = Field(None, max_length=20, description="AI整改建议审核状态")


class HazardReportResponse(HazardReportBase):
    """隐患报告响应"""

    id: uuid.UUID
    rectification_status: str
    status: str
    # ── 三级复核（仅状态，审核人/时间由系统自动记录）──
    verify_level_1_status: str = "pending"
    verify_level_2_status: str = "pending"
    verify_level_3_status: str = "pending"
    # ── AI 流程字段 ──
    ai_node_progress: str = "pending_input"
    overall_status: str = "draft"
    ai_error_message: str | None = None
    script1_review_status: str = "pending"
    script2_review_status: str = "pending"
    # ── AI 整改初审 ──
    ai_review_result: dict | None = None
    ai_review_status: str = "pending"
    ai_review_completed_at: datetime | None = None
    ai_generated: bool = False
    created_at: datetime
    updated_at: datetime
    # ── 飞书通知追踪 ──
    rectification_notified_at: datetime | None = None
    rectification_notify_status: str | None = None
    rectification_notify_error: str | None = None
    review_notified_at: datetime | None = None
    review_notified_level: int | None = None
    review_notify_status: str | None = None
    review_notify_error: str | None = None

    class Config:
        from_attributes = True


class HazardReportRunAIRequest(BaseModel):
    """执行隐患AI工作流请求（AI从已有数据读取上下文）"""

    pass


class DepartmentLeaderResponse(BaseModel):
    """部门负责人查询响应"""

    department: str = Field(..., description="部门名称")
    leader_name: str | None = Field(None, description="负责人姓名")
    leader_id: str | None = Field(None, description="负责人 UUID")


class DepartmentSafetyOfficerResponse(BaseModel):
    """部门分管安全员查询响应"""

    department: str = Field(..., description="部门名称")
    safety_officer_name: str | None = Field(None, description="安全员姓名")
    safety_officer_id: str | None = Field(None, description="安全员 UUID")


