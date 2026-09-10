"""相关方准入 AI 审核插件 — 输入/输出数据结构定义。

当前仅审核「安全管理协议」维度（agreement）；企业营业执照(license) /
现场作业保险凭证(insurance) 维度预留待开发（字段可选，暂不产出）。
输出：agreement 维度结论 + overall_conclusion + overall_report +
defect_categories（安全管理协议-A/B/C/D 四类，带附件前缀）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewConclusion(StrEnum):
    """维度结论（与 Bitable 单选列选项一致）"""

    APPROVED = "审核通过"
    NEEDS_SUPPLEMENT = "需补充完善"
    REJECTED = "审核不通过"


class AdmissionDimensionResult(BaseModel):
    """单维度审核结果"""

    conclusion: ReviewConclusion = Field(
        ..., description="结论: 审核通过/需补充完善/审核不通过"
    )
    report: str = Field(..., description="审核报告（分类分节：一、安全管理协议-X类 + 编号明细）")
    defects: list[str] = Field(default_factory=list, description="不符合项明细")


class AdmissionReviewInput(BaseModel):
    """AI 审核输入 — 相关方基本信息 + 协议文本/视觉描述 + RAG 知识"""

    company_name: str = Field(default="", description="作业单位名称")
    related_party_type: str = Field(
        default="", description="相关方类型: 承包商/合作类相关方/劳务派遣/其他相关方"
    )
    agreement_text: str = Field(default="", description="安全管理协议文本提取结果")
    agreement_vision_desc: str = Field(
        default="", description="安全管理协议视觉描述（公章/签字/骑缝章）"
    )
    # 预留维度（待开发）：企业营业执照 / 现场作业保险凭证
    license_text: str = Field(default="", description="（预留）企业营业执照文本提取结果")
    license_vision_desc: str = Field(default="", description="（预留）企业营业执照视觉描述")
    insurance_text: str = Field(default="", description="（预留）现场作业保险凭证文本提取结果")
    insurance_vision_desc: str = Field(default="", description="（预留）现场作业保险凭证视觉描述")
    knowledge_md: str = Field(default="", description="RAG 检索的法规上下文（Markdown）")


class AdmissionReviewOutput(BaseModel):
    """AI 审核完整输出 — 当前仅协议维度 + 总体结论"""

    agreement: AdmissionDimensionResult = Field(..., description="安全管理协议审核")
    license: AdmissionDimensionResult | None = Field(
        default=None, description="企业营业执照审核（预留，待开发）"
    )
    insurance: AdmissionDimensionResult | None = Field(
        default=None, description="现场作业保险凭证审核（预留，待开发）"
    )
    overall_conclusion: ReviewConclusion = Field(
        ..., description="总体结论（当前即协议维度结论）"
    )
    overall_report: str = Field(default="", description="综合退回话术（分类分节格式）")
    defect_categories: list[str] = Field(
        default_factory=list,
        description="不符合原因分类多选: 安全管理协议-A基础信息类/B有效期类/C签章类/D骑缝章类",
    )
