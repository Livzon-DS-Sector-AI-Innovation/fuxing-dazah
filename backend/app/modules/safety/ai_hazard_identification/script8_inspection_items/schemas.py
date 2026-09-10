"""脚本8 排查内容生成 — 输入/输出数据模型。

职责: 根据 4 类现有控制措施（人工），生成 4 类现场排查检查项（AI）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class InspectionItemsInput(BaseModel):
    """脚本8 输入：4 类现有控制措施（人工确认值）。"""

    engineering_controls: str = Field(..., description="现有工程控制措施（人工）")
    management_controls: str = Field(..., description="现有管理控制措施（人工）")
    ppe: str = Field(..., description="现有个人防护措施（人工）")
    emergency_measures: str = Field(..., description="现有应急措施（人工）")


class InspectionItemsOutput(BaseModel):
    """脚本8 输出：4 类现场排查检查项（AI）。"""

    engineering_items: str = Field(..., description="工程措施排查内容（AI）")
    management_items: str = Field(..., description="管理措施排查内容（AI）")
    ppe_items: str = Field(..., description="个人防护措施排查内容（AI）")
    emergency_items: str = Field(..., description="应急措施排查内容（AI）")
