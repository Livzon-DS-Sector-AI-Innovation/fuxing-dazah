"""溯源 API 契约。合并场景下谱系是 DAG，用 批次列表 + 谱系边列表 表达。

除同路线谱系边（batch_links）外，还支持跨路线物料边（link_type="material"）：
投料消耗引用上游批次产出，物料边方向与谱系一致，
parent = 产出批次（上游），child = 消耗批次（下游）。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class TraceExecutionBrief(BaseModel):
    node_name: str
    status: str
    owner_name: str | None
    started_at: datetime
    finished_at: datetime | None
    is_deviation: bool
    abnormal_count: int


class TraceBatch(BaseModel):
    id: uuid.UUID
    batch_no: str
    product_id: uuid.UUID
    product_name: str | None = None
    status: str
    quantity: float | None
    unit: str | None
    current_stage_name: str | None = None
    executions: list[TraceExecutionBrief] = []


class TraceLink(BaseModel):
    """谱系边（link_type="lineage"）或物料边（link_type="material"）。

    lineage 字段：edge_id / allocated_qty / is_deviation；
    material 字段：intermediate_type_id / intermediate_type_name /
    intermediate_batch_no / quantity（同对批次同物料聚合求和）/ unit。
    """

    parent_batch_id: uuid.UUID
    child_batch_id: uuid.UUID
    link_type: str = "lineage"
    # lineage 专属
    edge_id: uuid.UUID | None = None
    allocated_qty: float | None = None
    is_deviation: bool = False
    # material 专属
    intermediate_type_id: uuid.UUID | None = None
    intermediate_type_name: str | None = None
    intermediate_batch_no: str | None = None
    quantity: float | None = None
    unit: str | None = None


class TraceOut(BaseModel):
    root_batch_id: uuid.UUID
    batches: list[TraceBatch]
    links: list[TraceLink]
