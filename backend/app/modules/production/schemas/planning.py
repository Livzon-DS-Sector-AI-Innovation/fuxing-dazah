"""计划中枢 API 契约。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

# ── Demand ──

class DemandCreate(BaseModel):
    demand_no: str | None = Field(default=None, max_length=30, description="留空自动生成")
    source_type: str = Field(default="manual", pattern="^(manual|sales_order|forecast|internal)$")
    source_ref: str | None = Field(default=None, max_length=100)
    product_id: uuid.UUID
    product_name: str = Field(max_length=200)
    demanded_quantity: float = Field(gt=0)
    unit: str = Field(max_length=20)
    demand_date: date
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    customer_name: str | None = Field(default=None, max_length=100)
    remark: str | None = None


class DemandUpdate(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    demanded_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    demand_date: date | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    customer_name: str | None = Field(default=None, max_length=100)
    remark: str | None = None


class DemandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    demand_no: str
    source_type: str
    source_ref: str | None
    product_id: uuid.UUID
    product_name: str
    demanded_quantity: float
    allocated_quantity: float
    fulfilled_quantity: float
    unit: str
    demand_date: date
    priority: str
    status: str
    customer_name: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_quantity(self) -> float:
        return self.demanded_quantity - self.allocated_quantity


class DemandDetailOut(DemandOut):
    allocations: list["DemandAllocationOut"] = []


# ── PlanOrder ──

class StageConfigItem(BaseModel):
    """工段配置/时长项 — ponytail: plan_order.stage_config 和 plan_item.stage_durations 共用"""
    stage_name: str = Field(max_length=100)
    duration_hours: float = Field(gt=0, description="预计完成时长（小时）")
    color: str = Field(pattern="^#[0-9a-fA-F]{6}$", description="显示颜色 hex")


class PlanOrderCreate(BaseModel):
    order_no: str | None = Field(default=None, max_length=30, description="留空自动生成")
    title: str = Field(max_length=200)
    product_id: uuid.UUID
    route_id: uuid.UUID
    stage_config: list[StageConfigItem] | None = None
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanOrderUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    product_id: uuid.UUID | None = None
    route_id: uuid.UUID | None = None
    stage_config: list[StageConfigItem] | None = None
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_no: str
    title: str
    plan_version: int
    status: str
    product_id: uuid.UUID | None = None
    route_id: uuid.UUID | None = None
    stage_config: list[StageConfigItem] | None = None
    scheduled_start: date | None
    scheduled_end: date | None
    priority: str
    remark: str | None
    created_at: datetime
    updated_at: datetime


class PlanOrderDetailOut(PlanOrderOut):
    items: list["PlanItemOut"] = []
    demand_allocations: list["DemandAllocationOut"] = []
    change_logs: list["PlanOrderChangeLogOut"] = []


# ── PlanOrder Change ──


class PlanItemChangeItem(BaseModel):
    """计划项变更条目：id 非空为更新，id 为空为新增。"""
    id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    product_name: str | None = Field(default=None, max_length=200)
    route_id: uuid.UUID | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    planned_quantity: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    batch_no: str | None = Field(default=None, max_length=50)
    stage_durations: list[StageConfigItem] | None = None
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None
    sort_order: int | None = None


class PlanOrderChangeRequest(BaseModel):
    """计划单变更请求。"""
    change_reason: str = Field(..., min_length=1, description="变更原因")
    title: str | None = Field(default=None, max_length=200)
    stage_config: list[StageConfigItem] | None = None
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None
    items_upsert: list[PlanItemChangeItem] | None = None
    items_delete: list[uuid.UUID] | None = None


class RouteNodeBrief(BaseModel):
    """进度条用的轻量工序节点，不带 fields/intermediates 避免懒加载。"""
    name: str
    stage_name: str | None = None


class PlanItemBatchProgress(BaseModel):
    """计划项对应批次的生产进度（单分支最远工序）。"""
    batch_no: str
    batch_status: str
    latest_stage: str | None = None
    latest_stage_status: str | None = None
    route_nodes: list[RouteNodeBrief] | None = None


class PlanOrderChangeLogOut(BaseModel):
    """变更日志出参。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_version: int
    change_reason: str
    changed_by: uuid.UUID | None = None
    changed_by_name: str = ""
    created_at: datetime


# ── PlanItem ──

class PlanItemCreate(BaseModel):
    product_id: uuid.UUID
    product_name: str = Field(max_length=200)
    route_id: uuid.UUID | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    planned_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    batch_no: str = Field(max_length=50)
    stage_durations: list[StageConfigItem] | None = None
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanItemUpdate(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    route_id: uuid.UUID | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    planned_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    batch_no: str | None = Field(default=None, max_length=50)
    stage_durations: list[StageConfigItem] | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanItemScheduleIn(BaseModel):
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    sort_order: int | None = None


class PlanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_order_id: uuid.UUID
    item_no: int
    product_id: uuid.UUID
    product_name: str
    route_id: uuid.UUID | None
    equipment_id: str | None
    planned_quantity: float | None
    unit: str | None
    batch_no: str | None
    stage_durations: list[StageConfigItem] | None = None
    planned_start: datetime | None
    planned_end: datetime | None
    status: str
    priority: str
    sort_order: int
    remark: str | None
    created_at: datetime
    updated_at: datetime

    # ponytail: __init__ 注入 allocations，不另建 Detail 类
    allocations: list["PlanAllocationOut"] = []
    demand_allocations: list["DemandAllocationOut"] = []
    batch_progress: PlanItemBatchProgress | None = None  # 新增


# ── PlanAllocation ──

class PlanAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_item_id: uuid.UUID
    batch_id: uuid.UUID
    allocated_quantity: float | None = None
    # ponytail: batch 简要信息只注入 batch_status/batch_no，不深层展开
    batch_no: str = ""
    batch_status: str = ""


# ── DemandAllocation ──

class DemandAllocationCreate(BaseModel):
    plan_item_id: uuid.UUID
    allocated_quantity: float = Field(gt=0)


class DemandAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    demand_id: uuid.UUID
    plan_item_id: uuid.UUID
    allocated_quantity: float
    # 填充字段（由 service 层注入）
    demand_no: str = ""
    plan_order_no: str = ""
    item_no: int = 0
    intermediate_type_name: str = ""


# ── 排程视图 ──

class ScheduleViewItem(BaseModel):
    """排程甘特图单条数据。"""
    plan_order_id: uuid.UUID
    order_no: str
    order_title: str
    order_status: str
    order_priority: str
    order_scheduled_start: date | None
    order_scheduled_end: date | None
    item_id: uuid.UUID
    item_no: int
    product_id: uuid.UUID
    product_name: str
    equipment_id: str | None
    planned_quantity: float | None
    unit: str | None
    batch_no: str | None
    route_id: uuid.UUID | None
    stage_durations: list[StageConfigItem] | None = None
    planned_start: datetime | None
    planned_end: datetime | None
    item_status: str
    item_priority: str


# ── 追溯树 ──

class TraceNode(BaseModel):
    """需求全链路追溯：自引用树节点。"""
    type: str  # "demand" | "plan_item" | "batch"
    id: uuid.UUID
    label: str
    quantity: float | None = None
    unit: str | None = None
    status: str | None = None
    children: list["TraceNode"] = []
