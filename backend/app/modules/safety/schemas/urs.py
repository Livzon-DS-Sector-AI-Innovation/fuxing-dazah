"""URS 智能审核 — Pydantic 请求/响应 Schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── 枚举选项 ──

EQUIPMENT_CATEGORY_OPTIONS = [
    {"value": "采样系统", "label": "采样系统"},
    {"value": "反应釜", "label": "反应釜"},
    {"value": "泵", "label": "泵"},
    {"value": "离心机", "label": "离心机"},
    {"value": "干燥设备", "label": "干燥设备"},
    {"value": "储罐", "label": "储罐"},
    {"value": "实验室仪器", "label": "实验室仪器"},
    {"value": "其他", "label": "其他"},
]

PROCUREMENT_PURPOSE_OPTIONS = [
    {"value": "新增", "label": "新增"},
    {"value": "更换", "label": "更换"},
    {"value": "技术改造", "label": "技术改造"},
]

URS_STATUS_OPTIONS = [
    {"value": "draft", "label": "草稿"},
    {"value": "assessing", "label": "评估中"},
    {"value": "human_review", "label": "人工复核"},
    {"value": "item_review", "label": "逐条审核"},
    {"value": "approved", "label": "已通过"},
    {"value": "rejected", "label": "已驳回"},
    {"value": "appeal", "label": "申诉中"},
    {"value": "closed", "label": "已闭环"},
]

RISK_LEVEL_OPTIONS = [
    {"value": "high", "label": "高风险"},
    {"value": "medium", "label": "中风险"},
    {"value": "low", "label": "低风险"},
]

RISK_DIMENSION_KEYS = ["mechanical", "electrical", "data", "environmental", "chemical"]


# ── 请求 ──


class URSCreate(BaseModel):
    equipment_name: str = Field(..., min_length=1, max_length=256, description="设备名称")
    equipment_category: str | None = Field(None, max_length=64, description="设备类别")
    department: str | None = Field(None, max_length=128, description="申请部门")
    applicant_name: str | None = Field(None, max_length=128, description="申请人姓名")
    procurement_purpose: str | None = Field(None, max_length=32, description="采购用途")
    urs_content: str | None = Field(None, description="URS 正文")
    attachment_path: str | None = Field(None, max_length=500, description="附件路径")
    notes: str | None = Field(None, description="备注")


class URSUpdate(BaseModel):
    equipment_name: str | None = Field(None, max_length=256)
    equipment_category: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    applicant_name: str | None = Field(None, max_length=128)
    procurement_purpose: str | None = Field(None, max_length=32)
    urs_content: str | None = None
    attachment_path: str | None = Field(None, max_length=500)
    notes: str | None = None


class URSAssessmentConfirm(BaseModel):
    comment: str | None = Field(None, description="人工复核意见")
    corrections: dict[str, str] | None = Field(
        None, description="风险画像修正 {dimension: level}，修正后自动重跑适配"
    )


class URSItemReview(BaseModel):
    item_id: uuid.UUID = Field(..., description="审核条目 ID")
    verdict: str = Field(..., description="passed/failed")
    comment: str | None = None
    rectification_required: bool = False


class URSItemReviewBatch(BaseModel):
    items: list[URSItemReview] = Field(default_factory=list)


class URSAppeal(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000, description="申诉理由")


# ── 响应 ──


class URSReportResponse(BaseModel):
    id: uuid.UUID
    urs_no: str
    equipment_name: str
    equipment_category: str | None = None
    department: str | None = None
    applicant_name: str | None = None
    procurement_purpose: str | None = None
    urs_content: str | None = None
    attachment_path: str | None = None
    notes: str | None = None

    risk_profile: dict | None = None
    overall_risk_level: str | None = None
    risk_profile_reasoning: str | None = None
    ai_confidence: float | None = None
    human_review_comment: str | None = None

    review_result: dict | None = None
    score: float | None = None
    grade: str | None = None
    conclusion: str | None = None
    rectification_requirements: list | None = None

    review_status: str = "draft"
    ai_error_message: str | None = None
    ai_assessment_status: str = "pending"
    ai_assessment_completed_at: datetime | None = None

    appeal_reason: str | None = None
    appeal_result: dict | None = None

    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class URSStandardItemResponse(BaseModel):
    id: uuid.UUID
    urs_id: uuid.UUID
    item_no: str
    category: str
    risk_dimension: str | None = None
    standard_title: str
    standard_ref: str | None = None
    is_veto: bool = False
    source: str = "seed"
    applicability: str = "recommended"
    applicability_reason: str | None = None
    review_status: str = "pending"
    review_comment: str | None = None
    ai_suggestion: str | None = None
    rectification_required: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


class URSReviewDocumentResponse(BaseModel):
    id: uuid.UUID
    resource_type: str = "urs_report"
    resource_id: uuid.UUID
    doc_type: str
    title: str
    content_json: dict | None = None
    version: int = 1
    feishu_doc_url: str | None = None
    feishu_doc_status: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class URSStatsResponse(BaseModel):
    total: int = 0
    high_risk: int = 0
    approved: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
