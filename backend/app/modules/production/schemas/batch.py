"""批次 API 契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.production.schemas.execution import ExecutionOut


class BatchCreate(BaseModel):
    batch_no: str = Field(max_length=50)
    product_id: uuid.UUID
    route_id: uuid.UUID
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    remark: str | None = None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_no: str
    product_id: uuid.UUID
    route_id: uuid.UUID
    route_name: str = ""
    route_version: int = 0
    status: str
    quantity: float | None
    unit: str | None
    entry_node_id: uuid.UUID | None
    remark: str | None
    creation_type: str = "direct"
    plan_version: int | None = None
    created_at: datetime
    updated_at: datetime


class ChildBatchIn(BaseModel):
    batch_no: str = Field(max_length=50)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=20)


class DeriveIn(BaseModel):
    """分裂 / 1→1 换号：edge_id 为空视为偏离，必填 deviation_reason。"""

    edge_id: uuid.UUID | None = None
    deviation_reason: str | None = None
    children: list[ChildBatchIn] = Field(min_length=1)


class MergeParentIn(BaseModel):
    batch_id: uuid.UUID
    allocated_qty: float | None = None


class MergeIn(BaseModel):
    parents: list[MergeParentIn] = Field(min_length=2)
    edge_id: uuid.UUID | None = None
    deviation_reason: str | None = None
    batch_no: str = Field(max_length=50)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    remark: str | None = None


class BatchDetailOut(BatchOut):
    executions: list[ExecutionOut] = []
