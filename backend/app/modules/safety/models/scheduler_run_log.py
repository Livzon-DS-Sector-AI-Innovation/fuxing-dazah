"""定时任务运行日志（Agent 任务运行中心，3.0 四期 1-D）。

与 `SchedulerJobRun`（scheduler_job_runs，每任务一行 upsert 去重表）分工：
本表 append-only 记录**每次尝试**（成功/失败/超时各一行，含耗时与错误
摘要），只服务监督页展示；调度去重/重试/告警仍走 scheduler_job_runs。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class SchedulerTaskRunLog(BaseModel):
    """单次定时任务运行记录（append-only，无业务写入方）。"""

    __tablename__ = "scheduler_task_run_log"
    __table_args__ = (
        Index(
            "ix_scheduler_task_run_log_job_started",
            "job_name",
            "started_at",
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="调度任务名（对应 SCHEDULED_JOBS.name）"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="本次尝试开始时间（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="本次尝试结束时间（UTC）"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="success",
        server_default="success",
        comment="success=成功 / failed=失败或超时",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="耗时（毫秒）"
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败摘要（异常类型+消息，截断 500 字符）"
    )
