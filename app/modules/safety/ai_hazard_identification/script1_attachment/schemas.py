"""脚本1 附件解析 — 输入/输出数据模型。

职责: 从 SOP/操作规程附件文本中提取基础作业信息。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AttachmentInput(BaseModel):
    """脚本1 输入：基础信息 + 附件文本（由 DocumentParser 解析后的纯文本）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    attachment_text: str | None = Field(
        None, description="附件文档解析后的纯文本内容"
    )


class AttachmentOutput(BaseModel):
    """脚本1 输出：基础作业活动信息（为危险源辨识提供依据）。"""

    specific_activity: str = Field(
        ..., description="具体作业活动及操作过程描述（做什么 + 怎么做）"
    )
    equipment_facilities: str = Field(
        ..., description="涉及的主要设备设施（含规格型号、材质、容量等参数）"
    )
    raw_auxiliary_materials: str = Field(
        ..., description="涉及的原辅料（含危化品、蒸汽、氮气、工艺用水等）"
    )
