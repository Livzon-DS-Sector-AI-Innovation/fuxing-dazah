"""AI隐患评分插件 — 输入/输出数据结构。

制度依据：SOPAQ01015-03《隐患排查治理制度》§10.3 打分标准 D=L×E×C×X。
档位枚举的 value 即制度分值（唯一权威）；AI 输出中文档位标签，
由 rules 映射回枚举。**总分由代码计算，AI 不给裸数字。**
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════
# 档位枚举（17 档，value=制度分值）
# ═══════════════════════════════════════════════════════════════════════════


class LikelihoodTier(StrEnum):
    """L 造成事故的可能性（§10.3）。"""

    VERY_LIKELY = "2.0"   # 非常可能
    LIKELY = "1.5"        # 可能
    UNLIKELY = "1.0"      # 可能性小


class ExposureTier(StrEnum):
    """E 工作人员接触隐患频率（§10.3）。"""

    CONTINUOUS = "2.0"    # 连续接触
    DAILY = "1.8"         # 每天几次接触
    WEEKLY = "1.6"        # 每周接触
    MONTHLY = "1.4"       # 每月接触
    YEARLY = "1.2"        # 每年接触
    RARE = "1.0"          # 很少接触


class ConsequenceTier(StrEnum):
    """C 可能造成事故的后果（§10.3）。"""

    CATASTROPHE = "25"    # 灾难
    VERY_SEVERE = "22"    # 非常严重
    SEVERE = "20"         # 严重
    MODERATE = "18"       # 一般
    MINOR = "15"          # 轻微


class DifficultyTier(StrEnum):
    """X 排查难度（§10.3）：该隐患被日常排查发现的难易。"""

    HARD = "1.0"          # 难
    FAIRLY_HARD = "0.99"  # 较难
    NORMAL = "0.98"       # 一般


class RiskBandEnum(StrEnum):
    """公司风险分级（§4.5 + 附件四/五）。"""

    HIGH = "H"
    MEDIUM = "M"
    LOW = "L"


# ═══════════════════════════════════════════════════════════════════════════
# 输入 / 输出模型
# ═══════════════════════════════════════════════════════════════════════════


class HazardScoringInput(BaseModel):
    """评分输入 — 纯文本、无图片、无 RAG；**不含上报人姓名/部门**（评分主体=隐患本身）。"""

    hazard_no: str | None = None
    description: str = Field(..., min_length=1, max_length=2000, description="隐患描述原文")
    key_defect: str | None = Field(None, description="①轮规范化隐患描述（AI）")
    hazard_type: str | None = Field(None, description="隐患分类 EN 枚举码（①轮）")
    hazard_category: str | None = Field(None, description="隐患类别 EN 枚举码 13 类（①轮）")
    hazard_level: str | None = Field(None, description="隐患级别 EN 枚举码（①轮）")
    major_hazard_basis: str | None = Field(None, description="隐患判定依据（AI）原文")
    department: str | None = Field(None, description="整改责任部门（隐患位置语境）")
    inspection_category: str | None = Field(None, description="检查类别（语境）")


class MajorHazardHit(BaseModel):
    """重大隐患判定命中（附件一/AQ3067/附件三）。"""

    hit: bool = False
    clauses: list[str] = Field(default_factory=list, description='如 ["附件一·五", "AQ3067·生产运行"]')


class HazardScoringOutput(BaseModel):
    """评分输出 — AI 只选档位；总分由 rules.compute_total 计算。"""

    likelihood: LikelihoodTier
    likelihood_reason: str = Field(..., min_length=1, max_length=120)
    exposure: ExposureTier
    exposure_reason: str = Field(..., min_length=1, max_length=120)
    consequence: ConsequenceTier
    consequence_reason: str = Field(..., min_length=1, max_length=120)
    difficulty: DifficultyTier
    difficulty_reason: str = Field(..., min_length=1, max_length=120)
    band: RiskBandEnum
    band_basis: str = Field(..., min_length=1, max_length=120, description="附件四/五条目引用")
    major_hazard: MajorHazardHit = Field(default_factory=MajorHazardHit)
    summary: str = Field(..., min_length=1, max_length=80, description="综合评语")

    # 明确不含 total_score —— 代码计算（对标 ai_urs_review「评分由代码算」）

    @model_validator(mode="after")
    def _strip_reasons(self) -> Self:
        # AI 可能带前后空白；去壳后为空的已在 min_length 拦截
        self.likelihood_reason = self.likelihood_reason.strip()
        self.exposure_reason = self.exposure_reason.strip()
        self.consequence_reason = self.consequence_reason.strip()
        self.difficulty_reason = self.difficulty_reason.strip()
        self.band_basis = self.band_basis.strip()
        self.summary = self.summary.strip()
        return self


class PluginConfig(BaseModel):
    """插件配置（对标 ai_hazard_identification.PluginConfig 子集）。"""

    temperature: float = 0.05
