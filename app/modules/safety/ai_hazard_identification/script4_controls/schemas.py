"""脚本4 现有控制措施识别 — 输入/输出数据模型。

职责: 识别当前已存在的四维度控制措施。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ControlsInput(BaseModel):
    """脚本4 输入：基础信息 + 脚本1+2+3输出（经人工确认）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动")
    equipment_facilities: str = Field(..., description="设备设施")
    raw_auxiliary_materials: str = Field(..., description="原辅料")
    hazard_type: str = Field(..., description="危险类型")
    possible_accident: str = Field(..., description="可能导致事故")
    unsafe_behavior: str = Field(..., description="不规范行为")
    l_inherent: float | None = Field(None, description="L 固有")
    e_inherent: float | None = Field(None, description="E 固有")
    c_inherent: float | None = Field(None, description="C 固有")
    d_inherent: float | None = Field(None, description="D 固有")
    inherent_risk_level: str | None = Field(None, description="固有风险等级")
    inherent_risk_label: str | None = Field(None, description="固有风险等级名")


class ControlsOutput(BaseModel):
    """脚本4 输出：四维度现有控制措施。"""

    engineering_controls: str = Field(
        ..., description="现有工程控制措施（通风、联锁、报警、防护、隔离、泄压等）"
    )
    management_controls: str = Field(
        ..., description="现有管理控制措施（规程、培训、巡检、许可、交接班等）"
    )
    ppe: str = Field(
        ..., description="现有个人防护装备及使用要求"
    )
    emergency_measures: str = Field(
        ..., description="现有应急措施（处置流程、器材配置、报警撤离、急救）"
    )
