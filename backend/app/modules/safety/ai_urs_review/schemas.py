"""URS 智能审核插件 — 输入/输出数据结构定义。

四步流水线：
  ① RiskProfileAssessor  五维风险画像
  ② StandardAdapter      标准适配（seed + 知识库）
  ③ ItemReviewer         逐条审核（AI 预填）
  ④ ConclusionGenerator  结论生成（评分/等级/整改要求）

设计原则对标 ai_hazard_identification：低温度、强类型 Pydantic 输出、规则引擎校验。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════════
# 枚举定义
# ════════════════════════════════════════════════════════════════


class RiskLevelEnum(str, Enum):
    """风险等级 — 高/中/低"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApplicabilityEnum(str, Enum):
    """三级标准适配等级"""
    MANDATORY = "mandatory"          # 强制适用（否决项/底线条款）
    RECOMMENDED = "recommended"      # 建议适用
    NOT_APPLICABLE = "not_applicable"  # 不适用


class ReviewVerdictEnum(str, Enum):
    """逐条审核结论"""
    PASSED = "passed"
    FAILED = "failed"


class ConclusionEnum(str, Enum):
    """最终审核结论"""
    APPROVED = "approved"
    REJECTED = "rejected"


# ════════════════════════════════════════════════════════════════
# Step 1 — 五维风险画像
# ════════════════════════════════════════════════════════════════


class DimensionRisk(BaseModel):
    """单个维度的风险评估结果。"""

    level: RiskLevelEnum = Field(..., description="风险等级: high/medium/low")
    indicators: list[str] = Field(default_factory=list, description="命中指标列表")
    evidence: str = Field("", description="判定依据（从 URS 文本/设备描述引用）")


class RiskProfileInput(BaseModel):
    """适用性评估输入。"""

    equipment_name: str = Field(..., description="设备名称")
    equipment_category: str | None = Field(None, description="设备类别")
    urs_content: str = Field("", description="URS 正文（前 12000 字截断）")
    department: str | None = Field(None, description="申请部门")
    procurement_purpose: str | None = Field(None, description="采购用途")


class RiskProfileOutput(BaseModel):
    """适用性评估输出 — 五维风险画像 + 综合等级 + 置信度。"""

    mechanical: DimensionRisk
    electrical: DimensionRisk
    data: DimensionRisk
    environmental: DimensionRisk
    chemical: DimensionRisk
    overall_risk_level: RiskLevelEnum = Field(
        ..., description="综合等级: 任一 high→high；任一 medium→medium；否则 low"
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="评估置信度（0-1），<0.8 触发人工复核")
    reasoning: str = Field("", description="综合定级理由")


# ════════════════════════════════════════════════════════════════
# Step 2 — 标准适配
# ════════════════════════════════════════════════════════════════


class AdaptedItem(BaseModel):
    """单个标准条目的适配结果。"""

    item_no: str = Field(..., description="标准条目编号（如 S1.1）")
    applicability: ApplicabilityEnum = Field(..., description="适配等级")
    applicability_reason: str = Field("", description="适配依据")


class StandardAdaptationInput(BaseModel):
    """标准适配输入。"""

    equipment_name: str = Field(..., description="设备名称")
    risk_profile: RiskProfileOutput = Field(..., description="Step1 五维风险画像")
    items: list[dict] = Field(default_factory=list, description="标准条目 [{item_no, category, risk_dimension, standard_title, is_veto}]")


class StandardAdaptationOutput(BaseModel):
    """标准适配输出。"""

    items: list[AdaptedItem] = Field(default_factory=list, description="每条标准的适配结果")


# ════════════════════════════════════════════════════════════════
# Step 3 — 逐条审核（AI 预填）
# ════════════════════════════════════════════════════════════════


class ItemVerdict(BaseModel):
    """单条标准审核结论（AI 预填，人工确认后生效）。"""

    item_no: str = Field(..., description="标准条目编号")
    review_status: ReviewVerdictEnum = Field(..., description="通过/不通过")
    review_comment: str = Field("", description="审核意见")
    ai_suggestion: str = Field("", description="AI 建议（如补充 URS 缺失描述）")
    rectification_required: bool = Field(False, description="是否需整改")


class ItemReviewInput(BaseModel):
    """逐条审核输入。"""

    equipment_name: str = Field(..., description="设备名称")
    urs_content: str = Field("", description="URS 正文")
    items: list[dict] = Field(
        default_factory=list,
        description="适用条目 [{item_no, standard_title, standard_ref, applicability, category, is_veto}]",
    )


class ItemReviewOutput(BaseModel):
    """逐条审核输出。"""

    items: list[ItemVerdict] = Field(default_factory=list, description="每条标准的审核结论")


# ════════════════════════════════════════════════════════════════
# Step 4 — 结论生成
# ════════════════════════════════════════════════════════════════


class RectificationRequirement(BaseModel):
    """整改要求条目。

    字段名保留 responsible/deadline（对外序列化兼容），但二者均为**建议性质**：
    由 AI 辅助给出参考，最终责任人/期限需人工确认后方可生效。
    """

    item_no: str = Field(..., description="标准条目编号")
    requirement: str = Field(..., description="整改要求")
    responsible: str = Field(
        "", description="责任人（建议性质，需人工确认后才能生效）"
    )
    deadline: str = Field(
        "", description="期限（建议性质，需人工确认后才能生效）"
    )


class ConclusionInput(BaseModel):
    """结论生成输入。"""

    equipment_name: str = Field(..., description="设备名称")
    items: list[dict] = Field(
        default_factory=list,
        description="审核结果 [{item_no, category, applicability, review_status, review_comment, is_veto}]",
    )


class ConclusionOutput(BaseModel):
    """结论生成输出 — 评分/等级/结论/整改要求。"""

    score: float = Field(0.0, ge=0.0, le=100.0, description="百分制评分 = 通过项/适用项×100")
    grade: str = Field("D", description="等级: A≥90/B≥75/C≥60/D<60")
    conclusion: ConclusionEnum = Field(..., description="结论: approved/rejected")
    veto_break: bool = Field(False, description="是否有否决项不合格")
    summary: str = Field("", description="结论摘要")
    rectification_requirements: list[RectificationRequirement] = Field(
        default_factory=list, description="整改要求清单"
    )
