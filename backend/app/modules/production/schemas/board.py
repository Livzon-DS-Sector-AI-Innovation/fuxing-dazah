"""工序流程看板 API 契约（routes/{route_id}/process-board）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.production.schemas.execution import (
    EquipmentSnapshotOut,
    FieldValueOut,
)


class ProcessBoardNodeOut(BaseModel):
    """看板横轴上的一个工序节点。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_code: str
    name: str
    stage_name: str
    sort_order: int


class ProcessBoardPlannedItemOut(BaseModel):
    """看板计划批次列：已下达计划单中"已分配未执行"的实际批次及其计划来源。"""

    batch_id: uuid.UUID
    batch_no: str
    batch_status: str
    plan_order_id: uuid.UUID
    order_no: str
    plan_version: int
    item_id: uuid.UUID
    item_no: int
    planned_quantity: float | None
    unit: str | None
    planned_start: datetime | None
    planned_end: datetime | None
    item_status: str
    priority: str
    equipment_id: str | None


class ProcessBoardExecutionOut(BaseModel):
    """工序列中的一条批次（按批次当前位置归入其所在工序）。

    board_state 表示看板视角状态：
    - in_progress：该节点正在执行
    - waiting：该节点已完成、批次等待流转到下一工序（批次整体未完成）
    - aborted：该节点执行被中止
    """

    execution_id: uuid.UUID
    batch_id: uuid.UUID
    batch_no: str
    execution_seq: int
    status: str
    board_state: str
    owner_name: str | None
    started_at: datetime
    finished_at: datetime | None
    is_deviation: bool
    abnormal_count: int
    batch_status: str
    batch_quantity: float | None
    batch_unit: str | None
    equipments: list[EquipmentSnapshotOut] = []
    field_values: list[FieldValueOut] = []


class ProcessBoardOut(BaseModel):
    """工序流程看板整体数据。"""

    route_id: uuid.UUID
    route_name: str
    route_status: str
    nodes: list[ProcessBoardNodeOut]
    planned: list[ProcessBoardPlannedItemOut]
    columns: dict[uuid.UUID, list[ProcessBoardExecutionOut]]
