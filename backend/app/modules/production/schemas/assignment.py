import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.production.schemas.execution import MissingFieldOut

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

class StageNodeInfo(BaseModel):
    """工序面包屑节点：工段内单个工序及其进度状态。"""
    node_id: uuid.UUID
    node_name: str
    sort_order: int
    status: str  # "completed" | "in_progress" | "pending"


class MissingExecutionOut(BaseModel):
    """待完成批次中缺填必填字段的工序执行，供工作台直接补录。"""

    execution_id: uuid.UUID
    node_id: uuid.UUID
    node_name: str
    missing_required_fields: list[MissingFieldOut]


class WorkbenchItem(BaseModel):
    type: str  # pending_receive | pending_start | pending_complete | ready_to_complete
    batch_no: str | None = None
    batch_id: uuid.UUID | None = None
    product_name: str | None = None
    route_id: uuid.UUID
    route_name: str
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
    # 批次归属（多负责人产线隔离）：归属人姓名快照，无主批次为空
    batch_owner_name: str | None = None
    # 当前用户是否可操作该批次（归属自己/无主=True；归属他人=False，仅读）
    can_operate: bool = True
    # ready_to_complete 专用：该批次缺填必填字段的工序执行（工作台补录入口）
    missing_executions: list[MissingExecutionOut] = []
    started_at: str | None = None
    is_last_in_stage: bool = False  # 是否是工段内最后一个节点，完成即可提交批次
    # pending_start 工序的开始类型：normal / parallel / rework
    start_type: str | None = None
    # 工序面包屑：当前工段内所有工序及其完成状态
    stage_nodes: list[StageNodeInfo] = []


class AssignedNodeInfo(BaseModel):
    node_id: uuid.UUID
    node_name: str


class AssignedStageInfo(BaseModel):
    stage_name: str
    nodes: list[AssignedNodeInfo] = []


class AssignedRouteInfo(BaseModel):
    route_id: uuid.UUID
    route_name: str
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


# ── 计划批次 ──


class PlannedStageInfo(BaseModel):
    """工段时间信息，供前端渲染 mini 时间条。ponytail: 与 StageConfigItem 同构但独立避免循环导入。"""
    stage_name: str
    duration_hours: float
    color: str = "#cccccc"


class PlannedBatchItem(BaseModel):
    """计划批次（工作台排期区可见），纯只读。"""
    batch_id: uuid.UUID
    batch_no: str
    product_name: str | None = None
    route_id: uuid.UUID
    route_name: str
    plan_item_id: uuid.UUID
    plan_order_no: str
    planned_start: str | None = None
    planned_end: str | None = None
    stage_times: dict[str, str] = {}        # stage_name → ISO datetime
    current_stage: str | None = None         # 批次当前所在的工段
    current_stage_progress: str | None = None  # not_started | in_progress | completed
    stage_config: list[PlannedStageInfo] | None = None  # 工段时间配置（用于 timeline bar）
    is_first_stage_owner: bool = False       # 当前用户是否为路线第一工段负责人


class PlannedBatchOut(BaseModel):
    """计划批次查询响应。"""
    items: list[PlannedBatchItem] = []


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
