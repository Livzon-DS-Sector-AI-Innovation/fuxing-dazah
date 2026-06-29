"""Workflow Pydantic schemas — API 请求/响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════
# WorkflowDefinition
# ═══════════════════════════════════════════════════════════

class WorkflowDefCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    module_code: str = Field(..., min_length=1, max_length=64)
    graph: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class WorkflowDefUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    module_code: str | None = None
    graph: dict[str, Any] | None = None
    is_enabled: bool | None = None
    version: int | None = None


class WorkflowDefResponse(BaseModel):
    id: str
    name: str
    description: str | None
    module_code: str
    graph: dict[str, Any]
    is_enabled: bool
    version: int
    created_by: str | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
# WorkflowRun
# ═══════════════════════════════════════════════════════════

class WorkflowRunRequest(BaseModel):
    """触发工作流执行的请求体。"""
    inputs: dict[str, Any] = Field(default_factory=dict)
    entity_type: str | None = None
    entity_id: str | None = None


class NodeResultEntry(BaseModel):
    """单个节点的执行结果。"""
    status: str  # succeeded | failed | skipped
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tokens: int = 0


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    node_results: dict[str, NodeResultEntry]
    status: str
    total_tokens: int
    total_steps: int
    elapsed_time: float | None
    entity_type: str | None
    entity_id: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]
    total: int
    page: int
    page_size: int
