"""AI隐患识别插件 — 输入/输出数据结构定义。

所有类型严格对应《AI隐患识别工作流设计方案》第二章的字段规范。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════
# 枚举定义（与设计方案 2.2 节完全对齐）
# ═══════════════════════════════════════════════════════════════════════════


class HazardTypeEnum(str, Enum):
    """隐患分类 — 4 个枚举值"""
    UNSAFE_ACTION = "unsafe_action"       # 人的不安全行为
    UNSAFE_CONDITION = "unsafe_condition"  # 物的不安全状态
    ENVIRONMENTAL = "environmental"        # 环境的不安全因素
    MANAGEMENT_DEFECT = "management_defect"  # 管理的缺陷


class HazardCategoryEnum(str, Enum):
    """隐患类别 — 13 个枚举值"""
    EQUIPMENT = "equipment"                      # 设备设施
    HAZARDOUS_STORAGE = "hazardous_storage"      # 危化储存
    EMERGENCY_MGMT = "emergency_mgmt"            # 应急管理
    INSTRUMENT_ELECTRICAL = "instrument_electrical"  # 仪表+电气
    LIGHTNING_ANTISTATIC = "lightning_antistatic"  # 防雷防静电
    OCCUPATIONAL_HEALTH = "occupational_health"   # 职业健康+劳保防护
    VIOLATION_OPERATION = "violation_operation"   # 三违作业
    SIX_S = "six_s"                              # 6S
    LABEL_SIGNAGE = "label_signage"              # 标签标识
    PROCESS_MGMT = "process_mgmt"                # 工艺管理
    CONTRACTOR_DEFECT = "contractor_defect"      # 承包商缺陷
    DOCUMENTATION = "documentation"              # 内页资料
    SPECIAL_OPERATION = "special_operation"      # 特殊作业


class HazardLevelEnum(str, Enum):
    """隐患级别 — 3 个枚举值"""
    GENERAL = "general"    # 一般隐患
    SERIOUS = "serious"    # 较大隐患
    MAJOR = "major"        # 重大隐患


# ═══════════════════════════════════════════════════════════════════════════
# 输入模型
# ═══════════════════════════════════════════════════════════════════════════


class HazardIdentificationInput(BaseModel):
    """AI 隐患识别输入 — 对应设计方案 2.1 节"""

    hazard_id: uuid.UUID | None = Field(
        None, description="关联隐患记录 ID（无记录时可为空，用于独立测试）"
    )
    hazard_no: str | None = Field(
        None, description="隐患编号"
    )
    description: str = Field(
        ..., min_length=1, max_length=2000,
        description="人工填写的隐患描述文本"
    )
    department: str | None = Field(
        None, description="责任部门"
    )
    location: str | None = Field(
        None, description="地点/部位"
    )
    discovered_by_name: str | None = Field(
        None, description="检查人员姓名"
    )
    discovered_at: datetime | None = Field(
        None, description="检查日期"
    )
    defect_photos: list[str] = Field(
        default_factory=list,
        description="缺陷图片列表（本地路径 / URL / data URI）"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 输出模型
# ═══════════════════════════════════════════════════════════════════════════


class RectificationSuggestion(BaseModel):
    """整改建议 — 两层结构"""
    corrective: str = Field(
        ..., description="整改措施 — 针对隐患描述的最直接整改措施，含具体操作步骤、责任岗位、完成时限、验收标准"
    )
    preventive: str = Field(
        ..., description="预防措施 — 防止该隐患再次出现的预防措施，含制度修订、巡检纳入、台账建立、培训计划、考核方式"
    )


class HazardIdentificationOutput(BaseModel):
    """AI 隐患识别完整输出 — 对应设计方案 2.2 节"""

    # ── 核心识别 ──
    key_defect: str = Field(
        ..., max_length=200,
        description="隐患描述（AI）— 基于图片+文本综合分析的结构化描述"
    )
    hazard_type: HazardTypeEnum = Field(
        ..., description="隐患分类（AI）— 4 枚举"
    )
    hazard_category: HazardCategoryEnum = Field(
        ..., description="隐患类别（AI）— 13 枚举"
    )
    hazard_level: HazardLevelEnum = Field(
        ..., description="隐患级别（AI）— 3 枚举"
    )

    # ── 整改建议 ──
    rectification_suggestion: RectificationSuggestion = Field(
        ..., description="整改建议（AI）— 三分级"
    )

    # ── 判定依据 ──
    major_hazard_basis: str = Field(
        ..., min_length=5,
        description="隐患判定依据（AI）— 引用具体法规标准条文"
    )

    # ── 置信度（可选，用于质量评估）──
    confidence: float | None = Field(
        None, ge=0.0, le=1.0,
        description="AI 识别置信度（0-1）"
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
        True, description="是否启用多模态视觉分析"
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
