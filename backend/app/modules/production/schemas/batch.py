"""批次 API 契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    status: str
    quantity: float | None
    unit: str | None
    entry_node_id: uuid.UUID | None
    remark: str | None
    creation_type: str = "direct"
    plan_version: int | None = None
    first_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    owner_user_id: uuid.UUID | None = None
    owner_name: str | None = None


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


class ComputedFieldValueOut(BaseModel):
    field_key: str
    field_label: str
    unit: str | None
    value: float | None


class BatchOwnerTransferIn(BaseModel):
    """转移批次负责人。owner_user_id 为 None 表示清空负责人（设为无主共享）。

    权限复用 production:batch:submit；归属校验/工作台/产线兜底/提醒
    均实时读 batch.owner_user_id，改字段即完成权限转移。
    """

    owner_user_id: uuid.UUID | None = None


class BatchNoUpdateIn(BaseModel):
    """修改批次号。权限复用 production:batch:submit，不限批次状态。

    批号是批次身份级数据：展示/溯源/MCP 查询均实时读库，改名自动跟随；
    中间体产出记录里已固化的批号快照（intermediate_batch_no）不回写。
    """

    batch_no: str = Field(min_length=1, max_length=50)

    @field_validator("batch_no", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        # mode="before"：先 strip 再走 max_length 约束，避免「50 位有效批号 + 尾部空白」
        # 在约束阶段就被 422 拒绝（after 校验器排在约束之后）
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("批次号不能为空")
        return v


class BatchDetailOut(BatchOut):
    executions: list[ExecutionOut] = []
    computed_fields: list[ComputedFieldValueOut] = []
