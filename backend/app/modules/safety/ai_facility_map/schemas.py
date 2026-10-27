"""AI 地点→分区建议映射插件 — 输出模型（#2）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

CONFIDENCE_HIGH = "high"
CONFIDENCE_MID = "mid"
CONFIDENCE_LOW = "low"
VALID_CONFIDENCE = (CONFIDENCE_HIGH, CONFIDENCE_MID, CONFIDENCE_LOW)


class DistrictSuggestion(BaseModel):
    """单条建议：text 回显输入原文，dist_id 可空（无法判断不硬配）。"""

    text: str = Field(..., description="输入地点文本（原样回显）")
    dist_id: str | None = Field(
        None, description="建议分区 distId；不在 64 清单或无法判断为 None"
    )
    confidence: str = Field(
        CONFIDENCE_LOW, description="high|mid|low（AI 输出 medium 归一为 mid）"
    )
    reason: str = Field("", description="一句话判断依据")
