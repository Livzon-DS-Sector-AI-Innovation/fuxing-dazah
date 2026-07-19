"""中间体台账 API 契约。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 中间体字典 ──

class IntermediateTypeCreate(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=100)
    default_unit: str | None = Field(default=None, max_length=20)
    description: str | None = None


class IntermediateTypeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    default_unit: str | None = Field(default=None, max_length=20)
    description: str | None = None


class IntermediateTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str | None
    default_unit: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


# ── 节点-中间体绑定（模板层） ──

class NodeIntermediateIn(BaseModel):
    intermediate_type_id: uuid.UUID
    direction: Literal["output", "input"]
    unit_override: str | None = Field(default=None, max_length=20)
    required: bool = False
    is_product: bool = False
    sort_order: int = 0
    remark: str | None = None


class NodeIntermediateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    intermediate_type_id: uuid.UUID
    intermediate_type_name: str | None = None
    direction: str
    unit_override: str | None
    required: bool
    is_product: bool
    sort_order: int
    remark: str | None


# ── 产出/消耗记录（实例层） ──

class IntermediateOutputIn(BaseModel):
    intermediate_type_id: uuid.UUID
    quantity: float
    unit: str | None = Field(default=None, max_length=20)
    intermediate_batch_no: str | None = Field(default=None, max_length=100)
    is_product: bool = False
    remark: str | None = None


class IntermediateConsumptionIn(BaseModel):
    intermediate_type_id: uuid.UUID
    output_id: uuid.UUID
    quantity: float
    unit: str | None = Field(default=None, max_length=20)
    remark: str | None = None


class IntermediateOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    batch_no: str | None = None
    execution_id: uuid.UUID
    node_id: uuid.UUID
    node_name: str | None = None
    intermediate_type_id: uuid.UUID
    intermediate_type_name: str | None = None
    intermediate_batch_no: str | None
    quantity: float
    unit: str
    is_product: bool
    remark: str | None
    created_at: datetime


class IntermediateConsumptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    batch_no: str | None = None
    execution_id: uuid.UUID
    node_id: uuid.UUID
    node_name: str | None = None
    intermediate_type_id: uuid.UUID
    intermediate_type_name: str | None = None
    output_id: uuid.UUID
    output_batch_no: str | None = None
    quantity: float
    unit: str
    remark: str | None
    created_at: datetime
