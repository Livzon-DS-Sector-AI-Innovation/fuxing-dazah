"""Workflow ORM models — graphon 兼容的工作流定义与运行记录。

graph JSON 格式直接对接 graphon 的 Graph.init()，存储完整 DAG：
  {"nodes": [...], "edges": [...], "viewport": {...}}
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class WorkflowDefinition(BaseModel):
    """工作流定义 — graph JSON 完全兼容 graphon。

    graph 列存储完整的 DAG 结构（nodes + edges + viewport）。
    """

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        {"schema": "safety"}
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False)

    # graphon 兼容的 graph JSON
    graph: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
    )

    # 覆盖 BaseModel.created_by 的 ForeignKey — 不使用外键约束
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkflowRun(BaseModel):
    """工作流运行记录 — 每次执行产生一条记录。

    node_results 使用 JSONB 存储每个节点的执行详情：
      {node_id: {status, output, error, started_at, finished_at, tokens}}
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        {"schema": "safety"}
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )

    # 输入输出
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    node_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        server_default=text("'pending'"),
    )

    # 统计
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    total_steps: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    elapsed_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关联业务实体（可选）
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # 覆盖 BaseModel.created_by — 不使用外键约束
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
