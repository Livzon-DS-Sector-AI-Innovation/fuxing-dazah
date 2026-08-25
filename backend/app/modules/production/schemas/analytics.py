"""分析 API 契约。"""

import uuid
from datetime import datetime
from typing import Literal

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


class FieldTrendPoint(BaseModel):
    """字段趋势数据点（跨批次时间序列）。"""

    batch_no: str
    filled_at: datetime
    value: float


class StageSummaryColumn(BaseModel):
    """工段汇总平铺矩阵列定义（工序字段或计算字段）。"""

    node_id: uuid.UUID  # 工序节点 id，前端按节点分组表头
    node_code: str
    node_name: str
    field_key: str
    field_label: str
    unit: str | None
    kind: Literal["field", "computed"]
    col_key: str  # 行列扁平字典的键：{node_id}.{field_key}（node_code 仅路线内唯一，多路线会撞键）


class StageSummaryRow(BaseModel):
    """工段汇总平铺矩阵行：单批次一行，values/computed 键为 {node_id}.{field_key}。"""

    batch_id: uuid.UUID
    batch_no: str
    values: dict[str, float | str | bool | None]
    computed: dict[str, float | None]


class StageSummaryOut(BaseModel):
    """工段汇总平铺矩阵响应。"""

    columns: list[StageSummaryColumn]
    rows: list[StageSummaryRow]
