"""AI EHS 变更审核插件 — 输入/输出数据结构定义。

审核 4 个维度（对应飞书 Bitable 审批表的「-AI审核结论」「-AI审核报告」列）：
  申请变更原因(reason) / 变更计划内容(plan) / 预计效果(effect) / 变更风险评估及建议措施(risk)
每个维度输出 结论(审核通过/需补充完善/审核不通过) + 审核报告。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewConclusion(StrEnum):
    """维度审核结论（与 Bitable 单选列选项一致）"""

    PASS = "审核通过"
    SUPPLEMENT = "需补充完善"
    REJECT = "审核不通过"


class EhsReviewInput(BaseModel):
    """AI 审核输入 — 变更的基本信息 + 4 维度文本"""

    change_no: str | None = Field(None, description="变更编号")
    title: str = Field(default="", description="变更标题")
    change_type: str | None = Field(None, description="变更类型: process_tech/equipment_facility/management")
    change_grade: str | None = Field(None, description="变更等级: major/general")
    department: str | None = Field(None, description="责任部门（申请部门）")
    reason_text: str = Field(default="", description="申请变更原因文本")
    plan_text: str = Field(default="", description="变更计划内容文本")
    effect_text: str = Field(default="", description="预计效果文本")
    risk_text: str = Field(default="", description="变更风险评估及建议措施文本")


class EhsReviewDimension(BaseModel):
    """单维度审核结果"""

    conclusion: ReviewConclusion = Field(..., description="结论: 审核通过/需补充完善/审核不通过")
    report: str = Field(..., description="审核报告（说明/缺失项/改进建议）")


class EhsReviewOutput(BaseModel):
    """AI 审核完整输出 — 4 维度 + 预审意见"""

    reason: EhsReviewDimension = Field(..., description="申请变更原因审核")
    plan: EhsReviewDimension = Field(..., description="变更计划内容审核")
    effect: EhsReviewDimension = Field(..., description="预计效果审核")
    risk: EhsReviewDimension = Field(..., description="变更风险评估及建议措施审核")
    pre_review: str = Field(default="", description="AI 预审意见（总体结论与补料指引）")
