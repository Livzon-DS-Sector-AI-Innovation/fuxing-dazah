"""Safety ORM models."""

from typing import Any

from sqlalchemy import (
    Boolean,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 定时任务配置 ====================


class SchedulerTaskConfig(BaseModel):
    """定时任务配置覆写表（与 SCHEDULED_JOBS 按 job_name 匹配，NULL = 使用代码默认值）。"""

    __tablename__ = "scheduler_task_configs"
    __table_args__ = (
        Index(
            "uq_scheduler_task_configs_job_name",
            "job_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="调度任务名（对应 SCHEDULED_JOBS.name）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用",
    )
    hour: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行小时 0-23")
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行分钟 0-59")
    dow: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="星期 0-6（周一-周日），NULL=每天"
    )
    target_chat_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="飞书群聊 chat_id"
    )
    target_chat_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="群名（冗余，前端展示）"
    )
    retry_until_hour: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="补发窗口截止小时"
    )
    retry_until_minute: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="补发窗口截止分钟"
    )


class SchedulerConfigAudit(BaseModel):
    """定时任务配置变更审计表（append-only）。"""

    __tablename__ = "scheduler_config_audits"
    __table_args__ = (
        Index("idx_scheduler_config_audits_job_created", "job_name", "created_at"),
        {"schema": "safety"},
    )

    job_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="任务名（对应 SCHEDULED_JOBS.name）"
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable/run 等"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前配置（compact）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后配置（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人（当前用户 name，无则 None）"
    )


