"""职业健康 AI 工作流输出 Schemas — Pydantic v2。

对齐 backend-design.md §4.1：
- OhAbnormalIndicator：异常指标（原文值/单位/↑↓ 标记保留，数值不换算）
- OhExamReportParseOutput：体检报告智能解析全量输出
  （异常指标 / 结论分类 / 禁忌证 / 适配 / 建议 / 摘要）
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# 结论分类枚举值（与 OhAiConclusion 对齐，宽松存储为字符串便于 AI 输出校验）
CONCLUSION_CATEGORY_NORMAL = "normal"
CONCLUSION_CATEGORY_ABNORMAL_OTHER = "abnormal_other"
CONCLUSION_CATEGORY_CONTRAINDICATED = "contraindicated"
CONCLUSION_CATEGORY_SUSPECTED_OD = "suspected_od"
CONCLUSION_CATEGORY_OD_DIAGNOSED = "od_diagnosed"
CONCLUSION_CATEGORY_RE_EXAMINATION = "re_examination"

CONCLUSION_CATEGORIES: tuple[str, ...] = (
    CONCLUSION_CATEGORY_NORMAL,
    CONCLUSION_CATEGORY_ABNORMAL_OTHER,
    CONCLUSION_CATEGORY_CONTRAINDICATED,
    CONCLUSION_CATEGORY_SUSPECTED_OD,
    CONCLUSION_CATEGORY_OD_DIAGNOSED,
    CONCLUSION_CATEGORY_RE_EXAMINATION,
)

# 适配判定枚举值（与 OhFitness 对齐）
FITNESS_FIT = "fit"
FITNESS_FIT_WITH_RESTRICTION = "fit_with_restriction"
FITNESS_UNFIT = "unfit"

FITNESS_VALUES: tuple[str, ...] = (
    FITNESS_FIT,
    FITNESS_FIT_WITH_RESTRICTION,
    FITNESS_UNFIT,
)


class OhAbnormalIndicator(BaseModel):
    """异常指标（保留原文数值/单位/↑↓ 标记，不换算）"""

    name: str = Field(..., description="异常指标名称，如：谷丙转氨酶")
    value: str = Field(..., description="检测值（保留原文单位与 ↑↓ 标记，如 68U/L↑）")
    reference_range: str | None = Field(None, description="参考范围（原文，无则 null）")
    category: str = Field(..., description="指标类别: lab/vision/hearing/physique/other")
    severity: str = Field(..., description="异常程度: mild/moderate/severe")
    followup_suggestion: str | None = Field(
        None, description="建议随访动作（如：建议复查、建议专科就诊），无则 null"
    )

    # ── 宽容校验：模型偶发输出 null/数字，归一为合法值而非整单失败 ──
    @field_validator("name", "value", mode="before")
    @classmethod
    def _coerce_text(cls, v):
        if v is None:
            return ""
        return str(v)

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v):
        if v not in ("lab", "vision", "hearing", "physique", "other"):
            return "other"
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, v):
        if v not in ("mild", "moderate", "severe"):
            return "mild"
        return v


class OhExamReportParseOutput(BaseModel):
    """体检报告智能解析全量输出（对应 oh_health_exams.ai_parse_result）"""

    abnormal_indicators: list[OhAbnormalIndicator] = Field(
        default_factory=list, description="异常指标列表（无异常为空数组）"
    )
    conclusion_category: str = Field(
        ...,
        description="结论分类: normal/abnormal_other/contraindicated/suspected_od/od_diagnosed/re_examination",
    )
    contraindication_factors: list[str] = Field(
        default_factory=list, description="职业禁忌证涉及危害因素 [标准名]（只能从危害因素标准字典选取）"
    )
    contraindication_statement: str | None = Field(
        None, description="禁忌证相关结论原文逐字引用（禁止改写/编造）"
    )
    has_contraindication: bool = Field(
        ..., description="是否存在职业禁忌证（无法判定时 true 并标注需人工复核）"
    )
    fitness: str = Field(..., description="岗位适配判定: fit/fit_with_restriction/unfit")
    treatment_advice: list[str] = Field(
        default_factory=list,
        description="处理意见枚举: follow_up/transfer_post/medical_referral/ppe_strengthen/regular_monitor",
    )
    recommendations: list[str] = Field(
        default_factory=list, description="面向员工的健康建议（逐条，中文）"
    )
    summary_text: str = Field(..., description="总体解读摘要（200 字以内）")

    # ── 宽容校验：模型偶发输出 null/非法枚举 → 兜底归一（无法判定由业务层标记人工复核）──
    @field_validator("conclusion_category", mode="before")
    @classmethod
    def _coerce_conclusion(cls, v):
        if v not in CONCLUSION_CATEGORIES:
            return CONCLUSION_CATEGORY_ABNORMAL_OTHER
        return v

    @field_validator("fitness", mode="before")
    @classmethod
    def _coerce_fitness(cls, v):
        if v not in FITNESS_VALUES:
            return FITNESS_UNFIT
        return v

    @field_validator("summary_text", mode="before")
    @classmethod
    def _coerce_summary(cls, v):
        if v is None:
            return ""
        return str(v)

    @field_validator("abnormal_indicators", "contraindication_factors", "treatment_advice", "recommendations", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v] if v else []

    @field_validator("has_contraindication", mode="before")
    @classmethod
    def _coerce_bool(cls, v):
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "是")
        return bool(v)

    # chat_parsed 解析结果经 model_validate 时可能携带额外键，Pydantic v2 默认忽略
    model_config = {"extra": "ignore"}
