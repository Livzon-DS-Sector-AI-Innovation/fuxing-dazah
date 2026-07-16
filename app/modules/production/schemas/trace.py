"""溯源 API 契约。合并场景下谱系是 DAG，用 批次列表 + 谱系边列表 表达。"""

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
    status: str
    quantity: float | None
    unit: str | None
    executions: list[TraceExecutionBrief] = []


class TraceLink(BaseModel):
    parent_batch_id: uuid.UUID
    child_batch_id: uuid.UUID
    edge_id: uuid.UUID | None
    allocated_qty: float | None
    is_deviation: bool


class TraceOut(BaseModel):
    root_batch_id: uuid.UUID
    batches: list[TraceBatch]
    links: list[TraceLink]
