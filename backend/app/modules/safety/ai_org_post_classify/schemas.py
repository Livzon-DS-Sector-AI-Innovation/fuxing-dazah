"""AI 岗位族归类插件 — 输出模型（#4）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

CONFIDENCE_HIGH = "high"
CONFIDENCE_MID = "mid"
CONFIDENCE_LOW = "low"
VALID_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MID, CONFIDENCE_LOW)


class PostFamilyItem(BaseModel):
    """单条归类：post_name 回显输入原文，family 必须落在九族枚举。"""

    post_name: str = Field(..., description="输入岗位名（原样回显）")
    family: str = Field(..., description="标准岗位族（九族枚举之一）")
    confidence: str = Field(
        CONFIDENCE_LOW, description="high|mid|low（medium 归一 mid）"
    )
    note: str = Field("", description="一句话判断依据")
