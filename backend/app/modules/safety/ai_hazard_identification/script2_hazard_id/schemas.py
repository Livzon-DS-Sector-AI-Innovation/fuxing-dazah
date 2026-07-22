"""脚本2 AI危险源辨识 — 输入/输出数据模型。

职责: 从人机料法环五维度系统辨识危险源。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HazardIdInput(BaseModel):
    """脚本2 输入：基础信息 + 脚本1输出（经人工确认）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动（来自脚本1）")
    equipment_facilities: str = Field(..., description="设备设施（来自脚本1）")
    raw_auxiliary_materials: str = Field(..., description="原辅料（来自脚本1）")
    operation_frequency: str | None = Field(None, description="作业频次")
    operator_count: int | None = Field(None, description="操作人数")


class HazardIdOutput(BaseModel):
    """脚本2 输出：危险源辨识结果。"""

    hazard_type: str = Field(
        ..., description="危险类型（按 GB 6441《企业职工伤亡事故分类》归类）"
    )
    possible_accident: str = Field(
        ..., description="可能导致的最典型事故（含事故链条简述）"
    )
    unsafe_behavior: str = Field(
        ..., description="人的不规范作业行为表现（具体动作/状态描述）"
    )
