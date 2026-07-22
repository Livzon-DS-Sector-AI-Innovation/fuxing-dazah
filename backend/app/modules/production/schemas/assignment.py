import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ── 工段负责人 ──

class StageAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    stage_name: str = Field(max_length=100)
    route_id: uuid.UUID


class StageAssignmentOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    user_id: uuid.UUID
    stage_name: str
    route_id: uuid.UUID
    created_at: datetime


# ── 工序负责人 ──

class NodeAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    node_id: uuid.UUID
    route_id: uuid.UUID


class NodeAssignmentOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    user_id: uuid.UUID
    node_id: uuid.UUID
    route_id: uuid.UUID
    assigned_by: uuid.UUID
    created_at: datetime


class NodeAssigneeInfo(BaseModel):
    user_id: uuid.UUID
    name: str | None = None


# ── 工作台 ──

class WorkbenchItem(BaseModel):
    type: str  # pending_receive | pending_start | pending_complete | ready_to_complete
    batch_no: str | None = None
    batch_id: uuid.UUID | None = None
    product_name: str | None = None
    route_id: uuid.UUID
    route_name: str
    route_version: int | None = None
    node_id: uuid.UUID
    node_name: str
    stage_name: str | None = None
    predecessor_batches: list[str] = []
    node_assignees: list[NodeAssigneeInfo] = []
    # pending_receive 专用
    boundary_edge_id: uuid.UUID | None = None
    parent_batch_ids: list[uuid.UUID] = []
    # pending_complete 专用
    execution_id: uuid.UUID | None = None
    execution_seq: int | None = None
    owner_name: str | None = None
    started_at: str | None = None
    is_last_in_stage: bool = False  # 是否是工段内最后一个节点，完成即可提交批次


class AssignedNodeInfo(BaseModel):
    node_id: uuid.UUID
    node_name: str


class AssignedStageInfo(BaseModel):
    stage_name: str
    nodes: list[AssignedNodeInfo] = []


class AssignedRouteInfo(BaseModel):
    route_id: uuid.UUID
    route_name: str
    route_version: int | None = None
    product_name: str | None = None
    stages: list[AssignedStageInfo] = []


class RecentCompletedItem(BaseModel):
    batch_no: str | None = None
    batch_id: uuid.UUID | None = None
    product_name: str | None = None
    route_id: uuid.UUID
    route_name: str
    node_id: uuid.UUID
    node_name: str
    stage_name: str | None = None
    execution_id: uuid.UUID | None = None
    owner_name: str | None = None
    finished_at: str | None = None


class WorkbenchOut(BaseModel):
    role: str  # stage_owner | node_owner
    stage_names: list[str] = []
    assigned_routes: list[AssignedRouteInfo] = []
    items: list[WorkbenchItem] = []
    recent_completed: list[RecentCompletedItem] = []


# ── 接收并开始 ──

from app.modules.production.schemas.batch import ChildBatchIn  # noqa: E402
from app.modules.production.schemas.execution import ExecutionStartIn  # noqa: E402


class ReceiveAndStartIn(BaseModel):
    parent_batch_ids: list[uuid.UUID] = []
    edge_id: uuid.UUID | None = None
    deviation_reason: str | None = None
    children: list[ChildBatchIn] = []
    start_execution: bool = False
    execution: ExecutionStartIn | None = None
