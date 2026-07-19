"""中间体台账 API 契约。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── 中间体字典 ──

class IntermediateTypeCreate(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=100)
    default_unit: str | None = Field(default=None, max_length=20)
    description: str | None = None
    is_product: bool = False
    product_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_product_id_when_is_product(self):
        if self.is_product and self.product_id is None:
            raise ValueError("标记为成品时必须关联产品")
        return self


class IntermediateTypeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    default_unit: str | None = Field(default=None, max_length=20)
    description: str | None = None
    is_product: bool | None = None
    product_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_product_id_when_is_product(self):
        if self.is_product is True and self.product_id is None:
            raise ValueError("标记为成品时必须关联产品")
        return self


class IntermediateTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str | None
    default_unit: str | None
    description: str | None
    is_product: bool
    product_id: uuid.UUID | None
    product_name: str | None = None
    created_at: datetime
    updated_at: datetime


# ── 节点-中间体绑定（模板层） ──

class NodeIntermediateIn(BaseModel):
    intermediate_type_id: uuid.UUID
    direction: Literal["output", "input"]
    unit_override: str | None = Field(default=None, max_length=20)
    required: bool = False
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
    sort_order: int
    remark: str | None


# ── 产出/消耗记录（实例层） ──

class IntermediateOutputIn(BaseModel):
    intermediate_type_id: uuid.UUID
    quantity: float
    unit: str | None = Field(default=None, max_length=20)
    intermediate_batch_no: str | None = Field(default=None, max_length=100)
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


# ── 产出物出入库流水 ──

class MaterialMovement(BaseModel):
    type: Literal["output", "consumption"]
    batch_id: uuid.UUID
    batch_no: str | None
    node_name: str | None
    quantity: float
    unit: str
    intermediate_batch_no: str | None = None
    source_batch_no: str | None = None
    source_output_id: uuid.UUID | None = None
    created_at: datetime


class MaterialStockSummary(BaseModel):
    total_output: float
    total_consumed: float
    current_stock: float


class MaterialMovementsOut(BaseModel):
    material: IntermediateTypeOut
    movements: list[MaterialMovement]
    summary: MaterialStockSummary
