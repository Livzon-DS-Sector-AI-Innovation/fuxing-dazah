"""工艺路线（图）API 契约。整图保存用 node_code 做边的引用键。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FieldDefIn(BaseModel):
    field_key: str = Field(max_length=50)
    field_label: str = Field(max_length=100)
    field_group: str | None = Field(default=None, max_length=50)
    phase: Literal["start", "end"]
    data_type: Literal["numeric", "text", "boolean", "select"]
    options: list[str] | None = None
    unit: str | None = Field(default=None, max_length=20)
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    sort_order: int = 0


class FieldDefOut(FieldDefIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    phase: str  # type: ignore[assignment]
    data_type: str  # type: ignore[assignment]


class NodeIn(BaseModel):
    node_code: str = Field(max_length=50)
    name: str = Field(max_length=200)
    stage_name: str | None = Field(default=None, max_length=100)
    node_type: str = "process"
    sort_order: int = 0
    fields: list[FieldDefIn] = []


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_code: str
    name: str
    stage_name: str | None
    node_type: str
    sort_order: int
    fields: list[FieldDefOut] = []


class EdgeIn(BaseModel):
    from_node_code: str
    to_node_code: str
    edge_type: Literal["normal", "rework"] = "normal"
    is_batch_boundary: bool = False
    remark: str | None = Field(default=None, max_length=200)


class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    edge_type: str
    is_batch_boundary: bool
    remark: str | None


class RouteCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(max_length=200)


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    version: int
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class RouteGraphIn(BaseModel):
    nodes: list[NodeIn]
    edges: list[EdgeIn] = []


class RouteGraphOut(BaseModel):
    route: RouteOut
    nodes: list[NodeOut]
    edges: list[EdgeOut]
