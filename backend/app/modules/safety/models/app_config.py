"""Safety ORM models."""

from typing import Any

from sqlalchemy import (
    Boolean,
    Index,
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


# ==================== 应用配置中心 ====================


class AppConfigEntry(BaseModel):
    """应用配置表（一行一个配置键，key = 原 env 变量名）。

    生效优先级（见 app_config/store.py）：进程 env（非空）> DB 活行
    （enabled 且 value 非空）> registry 代码默认。env 优先是刻意设计：
    既有测试的 monkeypatch.setenv 隔离语义零回归（误发事故教训），且 env
    保留为运维应急通道；「迁移到 DB」通过清空 .env 中的键达成。
    """

    __tablename__ = "app_config_entries"
    __table_args__ = (
        Index(
            "uq_app_config_entries_key",
            "key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_app_config_entries_key", "key"),
        {"schema": "safety"},
    )

    key: Mapped[str] = mapped_column(
        String(128), nullable=False,
        comment="配置键（= 原 env 变量名，registry 注册，DB 只能改值不能新增键）",
    )
    value: Mapped[str] = mapped_column(
        String(1024), nullable=False, default="",
        comment="配置值（字符串形态；bool 存 true/false，int 存十进制）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false 时本行不参与生效值计算，视为无 DB 行）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AppConfigAudit(BaseModel):
    """应用配置变更审计表（append-only；secret 键值脱敏 ****后4位）。"""

    __tablename__ = "app_config_audits"
    __table_args__ = (
        Index("idx_app_config_audits_key_created", "key", "created_at"),
        Index("idx_app_config_audits_created", "created_at"),
        {"schema": "safety"},
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False, comment="配置键")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable/seed"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前 compact（secret 键值脱敏）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后 compact（secret 键值脱敏）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name；启动播种为 system"
    )
