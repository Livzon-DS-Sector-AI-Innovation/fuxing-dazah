"""R1 报警→隐患联动映射（links 瘦身表）。

§9.2 组件映射定案：候选/状态机部分由底座 agent_decisions 取代，本表只存
**业务关联**——报警 record_id ↔ 隐患 record_id/编号/处置人/任务 的映射与
触发时刻快照（追溯用）。状态不自管，由 decision 处置 + agent_tasks 现况
派生（REST join）。UNIQUE(alarm_domain, alarm_record_id) WHERE
is_deleted=false 是幂等第三道保险（Trigger 唯一约束与 decision 防重复开工
之外，兜执行器重试/重复转正不重复建隐患）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class AlarmHazardLink(BaseModel):
    """报警→隐患联动映射（safety schema；执行器查/建/回填，REST 查询）。"""

    __tablename__ = "alarm_hazard_links"
    __table_args__ = (
        Index(
            "uq_alarm_hazard_links", "alarm_domain", "alarm_record_id",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_alarm_hazard_links_task", "task_id"),
        {"schema": "safety"},
    )

    alarm_domain: Mapped[str] = mapped_column(
        String(16), comment="报警域（fire_alarm；中控随二期扩展）",
    )
    alarm_record_id: Mapped[str] = mapped_column(
        String(64), comment="报警 bitable record_id（幂等键）",
    )
    alarm_fingerprint: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="创建时 Trigger 指纹（追溯）",
    )
    hazard_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="隐患主表 record_id（create_record 返回）",
    )
    hazard_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="隐患编号（① 轮询分配后回读回填，展示用）",
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 superagent.agent_tasks.id",
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="处置来源（promoted→decision.resolved_by / auto）",
    )
    alarm_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, comment="触发时刻报警关键字段快照（原文 fields；追溯用）",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="执行器失败留痕（重试成功后清空）",
    )
    # is_deleted 由 BaseModel 提供（软删惯例；部分唯一索引谓词引用它）
