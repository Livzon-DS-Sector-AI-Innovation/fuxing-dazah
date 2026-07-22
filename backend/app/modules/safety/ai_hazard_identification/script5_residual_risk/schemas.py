"""脚本5 残余风险 LEC 评价 — 输入/输出数据模型。

评价「现有控制措施全部纳入考虑后」的残余风险。
LECOutput 复用自 script3_inherent_risk（三阶段共用结构）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    LECOutput,
)


class ResidualRiskInput(BaseModel):
    """脚本5 输入：全部前置字段 + 脚本4输出（经人工确认）。"""

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
    l_inherent: float | None = Field(None, description="L 固有")
    e_inherent: float | None = Field(None, description="E 固有")
    c_inherent: float | None = Field(None, description="C 固有")
    d_inherent: float | None = Field(None, description="D 固有")
    inherent_risk_level: str | None = Field(None, description="固有风险等级")
    inherent_risk_label: str | None = Field(None, description="固有风险等级名")
    existing_engineering_controls: str = Field(..., description="现有工程控制措施")
    existing_management_controls: str = Field(..., description="现有管理控制措施")
    existing_ppe: str = Field(..., description="现有个人防护措施")
    existing_emergency_measures: str = Field(..., description="现有应急措施")


class ResidualRiskOutput(BaseModel):
    """脚本5 输出：残余风险 LEC 评价结果。"""

    lec: LECOutput = Field(..., description="LEC 评价结果（残余风险）")
