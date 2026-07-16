"""节点执行 API 契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FieldValueIn(BaseModel):
    field_key: str
    value: bool | float | str | None = None


class FieldValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_key: str
    field_label: str
    unit: str | None
    phase: str
    value_text: str | None
    value_numeric: float | None
    value_bool: bool | None
    is_abnormal: bool
    remark: str | None


class EquipmentSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    equipment_id: uuid.UUID
    equipment_no: str
    equipment_name: str


class ExecutionStartIn(BaseModel):
    node_id: uuid.UUID
    owner_id: uuid.UUID | None = None
    owner_name: str | None = Field(default=None, max_length=50)
    equipment_ids: list[uuid.UUID] = []
    field_values: list[FieldValueIn] = []
    deviation_reason: str | None = None
    remark: str | None = None


class ExecutionCompleteIn(BaseModel):
    field_values: list[FieldValueIn] = []
    remark: str | None = None


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    node_id: uuid.UUID
    node_name: str | None = None  # service 组装时填充
    execution_seq: int
    status: str
    owner_id: uuid.UUID | None
    owner_name: str | None
    started_at: datetime
    started_by_name: str | None
    finished_at: datetime | None
    finished_by_name: str | None
    is_deviation: bool
    deviation_reason: str | None
    remark: str | None
    equipments: list[EquipmentSnapshotOut] = []
    field_values: list[FieldValueOut] = []


class NodeExecutionListItem(BaseModel):
    """工序视角的执行记录行（跨批次）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    batch_no: str
    execution_seq: int
    status: str
    owner_name: str | None
    started_at: datetime
    finished_at: datetime | None
    is_deviation: bool
    abnormal_count: int
