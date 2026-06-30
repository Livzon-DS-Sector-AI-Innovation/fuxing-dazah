"""AI 整改初审插件 — 输入/输出数据结构定义。

所有类型对应《AI隐患识别工作流设计方案》中整改审核维度的字段规范。
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════
# 枚举定义（5 个审核维度）
# ═══════════════════════════════════════════════════════════════════════════


class PhotoMatchLevel(StrEnum):
    """图片比对结果"""
    MATCHED = "matched"               # 整改后图片清晰展示缺陷已修复
    PARTIAL_MATCH = "partial_match"   # 部分修复，仍有遗留问题或角度不一致
    UNMATCHED = "unmatched"           # 图片与原始缺陷不匹配，或整改不到位
    NO_PHOTOS = "no_photos"           # 未提供整改后图片


class MeasureQualityLevel(StrEnum):
    """措施质量等级"""
    ADEQUATE = "adequate"        # 措施具体、可执行、有量化标准、有时间节点、有责任主体
    BASIC = "basic"              # 措施基本合理但缺乏细节（如缺少量化标准或时间节点）
    INADEQUATE = "inadequate"    # 措施空泛、不可操作、未针对根因


class ComplianceLevel(StrEnum):
    """标准合规等级"""
    COMPLIANT = "compliant"                     # 完全符合相关标准要求
    BASICALLY_COMPLIANT = "basically_compliant"  # 基本合规，存在轻微偏差
    NON_COMPLIANT = "non_compliant"              # 不合规，违反标准要求


class ReviewConclusion(StrEnum):
    """综合评审判定"""
    PASS = "通过"   # AI 初审通过，进入人工复核
    FAIL = "不通过"  # AI 初审不通过，返回责任人重新整改


# ═══════════════════════════════════════════════════════════════════════════
# 输入模型
# ═══════════════════════════════════════════════════════════════════════════


class RectificationReviewInput(BaseModel):
    """AI 整改初审输入 — 包含原始隐患信息 + 整改回复信息"""

    # ── 关联标识 ──
    hazard_id: uuid.UUID | None = Field(
        None, description="关联隐患记录 ID"
    )

    # ── 原始隐患信息（来自 HazardReport + AI 识别结果）──
    original_description: str = Field(
        ..., min_length=1, max_length=2000,
        description="原始隐患描述文本"
    )
    original_defect_photos: list[str] = Field(
        default_factory=list,
        description="原始缺陷图片（before），data URI 或 URL 列表"
    )
    key_defect: str | None = Field(
        None, max_length=200,
        description="AI 识别的关键缺陷描述"
    )
    hazard_type: str | None = Field(
        None, description="隐患分类: unsafe_action / unsafe_condition / environmental / management_defect"
    )
    hazard_category: str | None = Field(
        None, description="隐患类别: equipment / hazardous_storage / ... / special_operation"
    )
    hazard_level: str | None = Field(
        None, description="隐患级别: general / serious / major"
    )
    ai_rectification_suggestion: dict | None = Field(
        None, description="AI 生成的整改建议（两层结构: corrective / preventive）"
    )

    # ── 整改回复信息 ──
    rectification_reply: str = Field(
        ..., min_length=1,
        description="整改回复文本（纠正预防措施）"
    )
    rectification_photos: list[str] = Field(
        default_factory=list,
        description="整改后图片（after），data URI 或 URL 列表"
    )
    department: str | None = Field(
        None, description="责任部门"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 输出模型
# ═══════════════════════════════════════════════════════════════════════════


class RectificationReviewOutput(BaseModel):
    """AI 整改初审完整输出 — 3 个审核维度 + 综合结论"""

    # ── 图片比对 ──
    photo_match_analysis: str = Field(
        ..., min_length=1,
        description="before/after 图片对比分析：拍摄角度、修复痕迹、遗留问题的具体描述"
    )
    photo_match_level: PhotoMatchLevel = Field(
        ..., description="图片比对结论"
    )

    # ── 措施有效性 ──
    measure_quality_assessment: str = Field(
        ..., min_length=1,
        description="措施有效性评估：是否描述了具体可执行的操作、逻辑上能否消除隐患"
    )
    measure_quality_level: MeasureQualityLevel = Field(
        ..., description="措施有效性等级"
    )

    # ── 标准合规 ──
    standard_compliance: str = Field(
        ..., min_length=1,
        description="标准合规评估：整改措施是否符合法规知识库中的相关标准要求"
    )
    standard_compliance_level: ComplianceLevel = Field(
        ..., description="合规等级"
    )

    # ── 综合结论 ──
    review_conclusion: ReviewConclusion = Field(
        ..., description="综合审核结论"
    )
    review_comments: str = Field(
        ..., min_length=1,
        description="AI初审结果：通过/不通过"
    )

    # ── 置信度（可选）──
    confidence: float | None = Field(
        None, ge=0.0, le=1.0,
        description="AI 审核置信度（0-1）"
    )
    reasoning: str | None = Field(
        None, description="AI 推理过程简述（用于审计和调试）"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 质量评估
# ═══════════════════════════════════════════════════════════════════════════


class ValidationResult(BaseModel):
    """输出验证结果"""
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PluginConfig(BaseModel):
    """插件运行时配置"""
    temperature: float = Field(
        0.05, ge=0.0, le=1.0,
        description="AI 温度参数（低值保证可复现性）"
    )
    max_tokens: int = Field(
        4096, ge=512, le=16384,
        description="最大输出 token 数"
    )
    enable_vision: bool = Field(
        True, description="是否启用多模态视觉分析（对比 before/after 图片）"
    )
    enable_reasoning: bool = Field(
        False, description="是否请求 AI 输出推理过程（增加 token 消耗）"
    )
    enable_knowledge: bool = Field(
        True, description="是否启用法规知识库注入（RAG-lite）"
    )
    strict_mode: bool = Field(
        True, description="严格模式：规则验证失败时抛出异常"
    )
