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


# ==================== Bitable 配置中心 ====================


class BitableConnection(BaseModel):
    """Bitable 连接配置表（一行一表）。DB 为唯一权威；缺行/停用时 store 回退 registry 默认值。"""

    __tablename__ = "bitable_connections"
    __table_args__ = (
        Index(
            "uq_bitable_connections_domain_kind",
            "domain",
            "kind",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_bitable_connections_domain", "domain"),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="域 key（registry 注册，如 oh）"
    )
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="表类型 key（如 exam_registry）"
    )
    app_token: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="飞书多维表格 app_token（base/wiki 文档 token）"
    )
    table_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="表 table_id（central_alarm 为白名单主表）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（为 false 时 store 不返回给 handler，视为停用）",
    )
    extra_table_ids: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="仅 central_alarm：白名单其余表 table_id 列表（不含主表）"
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class BitableFieldMapping(BaseModel):
    """字段映射表（一行一域一 kind，JSONB 全量替换）。

    多表域（oh×6、msds×2、ehs×2、cert×3、drill×2）各表映射完全不同，按 kind 分行。
    """

    __tablename__ = "bitable_field_mappings"
    __table_args__ = (
        Index(
            "uq_bitable_field_mappings_domain_kind",
            "domain",
            "kind",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="域 key")
    kind: Mapped[str] = mapped_column(String(64), nullable=False, comment="表类型 key")
    mappings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, comment="字段映射列表，见 backend-design §2.2 JSONB 结构"
    )


class BitableConfigAudit(BaseModel):
    """Bitable 配置变更审计表（append-only，软删字段沿用但业务不做删除）。"""

    __tablename__ = "bitable_config_audits"
    __table_args__ = (
        Index("idx_bitable_config_audits_domain_created", "domain", "created_at"),
        {"schema": "safety"},
    )

    domain: Mapped[str] = mapped_column(String(64), nullable=False, comment="域 key")
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="表类型 key（域级操作时为 '*'）"
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable/resubscribe 等"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


