"""脚本7 措施后风险 LEC 评价 — 输入/输出数据模型。

评价「现有控制措施 + 已采纳建议措施」全部落地后的最终风险。
LECOutput 复用自 script3_inherent_risk（三阶段共用结构）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LECOutput,
)


class PostRiskInput(BaseModel):
    """脚本7 输入：全部前置字段 + 脚本6输出（经人工确认）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动")
    equipment_facilities: str = Field(..., description="设备设施")
    raw_auxiliary_materials: str = Field(..., description="原辅料")
    operation_frequency: str | None = Field(None, description="作业频次")
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
    control_level: str | None = Field(None)
    recommendation_content: str | None = Field(None, description="建议措施内容")
    recommendation_type: str | None = Field(None, description="建议措施类型")


class PostRiskOutput(BaseModel):
    """脚本7 输出：措施后风险 LEC 评价结果。"""

    lec: LECOutput = Field(..., description="LEC 评价结果（措施后风险）")
