"""分析 API 契约。"""

import uuid

from pydantic import BaseModel, ConfigDict


class StepCycleStat(BaseModel):
    """单工序周期统计"""
    model_config = ConfigDict(from_attributes=True)

    node_id: uuid.UUID
    node_name: str
    stage_name: str
    sort_order: int
    n: int
    avg_hours: float
    min_hours: float | None
    max_hours: float | None


class StepCycleResponse(BaseModel):
    """工序周期分析响应"""
    steps: list[StepCycleStat]
    total_batches: int
    sample_note: str | None = None
