"""脚本6 建议措施生成 — 输入/输出数据模型。

职责: 根据残余风险等级按控制层级原则提出建议措施。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecommendationInput(BaseModel):
    """脚本6 输入：全部前置字段 + 脚本5输出（经人工确认）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动")
    equipment_facilities: str = Field(..., description="设备设施")
    raw_auxiliary_materials: str = Field(..., description="原辅料")
    hazard_type: str = Field(..., description="危险类型")
    possible_accident: str = Field(..., description="可能导致事故")
    unsafe_behavior: str = Field(..., description="不规范行为")
    l_inherent: float | None = Field(None)
    e_inherent: float | None = Field(None)
    c_inherent: float | None = Field(None)
    d_inherent: float | None = Field(None)
    inherent_risk_level: str | None = Field(None)
    inherent_risk_label: str | None = Field(None)
    existing_engineering_controls: str = Field(..., description="现有工程控制")
    existing_management_controls: str = Field(..., description="现有管理控制")
    existing_ppe: str = Field(..., description="现有PPE")
    existing_emergency_measures: str = Field(..., description="现有应急措施")
    l_residual: float | None = Field(None)
    e_residual: float | None = Field(None)
    c_residual: float | None = Field(None)
    d_residual: float | None = Field(None)
    residual_risk_level: str | None = Field(None)
    residual_risk_label: str | None = Field(None)
    control_level: str | None = Field(None, description="管控等级")


class RecommendationOutput(BaseModel):
    """脚本6 输出：建议措施。"""

    needs_recommendation: str = Field(
        ..., description="是否需提出建议措施（是/否）"
    )
    recommendation_type: str = Field(
        ..., description="建议措施类型（工程控制/管理控制/PPE/应急/综合）"
    )
    recommendation_content: str = Field(
        ..., min_length=5, description="建议措施具体内容（可执行的详细描述）"
    )
    recommendation_priority: str = Field(
        ..., description="建议措施优先级（高/中/低）"
    )
