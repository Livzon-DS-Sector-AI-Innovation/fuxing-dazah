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


# ==================== AI 配置中心 ====================


class AiModelProfile(BaseModel):
    """AI 模型配置表（一行一组配置）。DB 为唯一权威；缺行/停用时 store 回退 env/registry 默认值。"""

    __tablename__ = "ai_model_profiles"
    __table_args__ = (
        Index(
            "uq_ai_model_profiles_profile",
            "profile",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_ai_model_profiles_profile", "profile"),
        {"schema": "safety"},
    )

    profile: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="profile key（registry 注册，如 text/text_backup/vision/embedding/rerank）",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="模型配置（默认值来自 registry.default_config，api_key 恒为空串不回显）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false 时读路径整行回落 env/registry 默认）",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiConfigAudit(BaseModel):
    """AI 配置变更审计表（append-only，软删字段沿用但业务不做删除）。"""

    __tablename__ = "ai_config_audits"
    __table_args__ = (
        Index("idx_ai_config_audits_profile_created", "profile", "created_at"),
        Index("idx_ai_config_audits_created", "created_at"),
        {"schema": "safety"},
    )

    profile: Mapped[str] = mapped_column(String(32), nullable=False, comment="profile key")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，api_key 已脱敏为 ****后4位）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，api_key 已脱敏为 ****后4位）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )


class AiScenarioConfig(BaseModel):
    """AI 场景配置表（一行一场景，只能改值不能新增场景）。

    缺行 = 默认开启（enabled=true、model_profile=NULL 按场景类型派生），无歧义；
    软删复刻 AiModelProfile 惯例（部分唯一索引防「软删→重建同场景」冲突）。
    """

    __tablename__ = "ai_scenario_configs"
    __table_args__ = (
        Index(
            "uq_ai_scenario_configs_scenario",
            "scenario",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_ai_scenario_configs_scenario", "scenario"),
        {"schema": "safety"},
    )

    scenario: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="场景 key（registry 注册，DB 只能改值不能新增场景）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        comment="是否启用（false = 熔断，统一入口抛 ScenarioDisabledError）",
    )
    model_profile: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="绑定 profile 名（text/text_backup/vision/embedding/rerank）；NULL = 按场景默认",
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class AiScenarioConfigAudit(BaseModel):
    """AI 场景配置变更审计表（append-only，软删字段沿用但业务不做删除）。

    相位不存任何密钥，``before_json``/``after_json`` 无需脱敏（复刻 AiConfigAudit）。
    """

    __tablename__ = "ai_scenario_config_audits"
    __table_args__ = (
        Index("idx_ai_scenario_config_audits_scenario_created", "scenario", "created_at"),
        Index("idx_ai_scenario_config_audits_created", "created_at"),
        {"schema": "safety"},
    )

    scenario: Mapped[str] = mapped_column(String(64), nullable=False, comment="对应场景")
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="动作: update/enable/disable"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更前（compact，{enabled, model_profile, note}，无密钥）"
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="变更后（compact，{enabled, model_profile, note}，无密钥）"
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作人 name"
    )

