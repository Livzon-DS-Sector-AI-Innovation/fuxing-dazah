"""节点执行 API 契约。"""

import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.time import APP_TZ, now
from app.modules.production.schemas.intermediate import (
    IntermediateConsumptionIn,
    IntermediateOutputIn,
)

# 分钟级时间选择器与服务器时钟之间允许的容差，避免"选当前分钟"被误判为未来
_FUTURE_TOLERANCE = timedelta(minutes=5)


def _normalize_manual_time(v: datetime | None) -> datetime | None:
    """归一化用户手填的工序时间：naive 按厂区时区解释，拒绝未来时间。"""
    if v is None:
        return v
    if v.tzinfo is None:
        v = v.replace(tzinfo=APP_TZ)
    if v > now() + _FUTURE_TOLERANCE:
        raise ValueError("时间不能晚于当前时间")
    return v


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
    intermediate_consumptions: list[IntermediateConsumptionIn] = []
    started_at: datetime | None = None  # 手填开始时间，留空用服务器当前时间

    @field_validator("started_at")
    @classmethod
    def _check_started_at(cls, v: datetime | None) -> datetime | None:
        return _normalize_manual_time(v)


class ExecutionCompleteIn(BaseModel):
    field_values: list[FieldValueIn] = []
    remark: str | None = None
    intermediate_outputs: list[IntermediateOutputIn] = []
    line_id: uuid.UUID | None = None
    finished_at: datetime | None = None  # 手填结束时间，留空用服务器当前时间

    @field_validator("finished_at")
    @classmethod
    def _check_finished_at(cls, v: datetime | None) -> datetime | None:
        return _normalize_manual_time(v)


class ExecutionBackfillIn(BaseModel):
    """工序结束后补录 end 阶段字段值。"""

    field_values: list[FieldValueIn] = []


class MissingFieldOut(BaseModel):
    """已结束工序尚未补录的必填字段（批次结束前须补齐）。"""

    field_key: str
    field_label: str


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
    missing_required_fields: list[MissingFieldOut] = []  # service 组装：已结束工序缺填的必填字段


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
