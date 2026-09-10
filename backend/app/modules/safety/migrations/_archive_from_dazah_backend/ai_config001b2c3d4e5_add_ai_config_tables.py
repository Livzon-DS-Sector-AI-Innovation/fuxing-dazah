"""add ai_model_profiles, ai_config_audits tables + seed

Revision ID: ai_config001b2c3d4e5
Revises: bitable001b2c3d4e5
Create Date: 2026-08-31 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_config001b2c3d4e5"
down_revision: str | None = "bitable001b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _profile_seed_rows() -> list[dict]:
    """播种 5 行 — 值单向导出自 registry.default_config（api_key 恒为空串，密钥不播种）。"""
    from app.modules.safety.ai_config.registry import iter_profiles

    rows: list[dict] = []
    for info in iter_profiles():
        cfg = dict(info.default_config)
        assert cfg.get("api_key", "") == "", f"{info.profile} api_key 默认必须为空串"
        rows.append(
            {
                "profile": info.profile,
                "config": cfg,
                "enabled": True,
                "note": f"{info.label}（registry 默认，api_key 留空走 env 兜底）",
            }
        )
    assert len(rows) == 5, f"registry profile 行数应为 5，实际 {len(rows)}"
    return rows


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    ai_model_profiles = op.create_table(
        "ai_model_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "profile",
            sa.String(32),
            nullable=False,
            comment="profile key（registry 注册，如 text/text_backup/vision/embedding/rerank）",
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="模型配置（默认值来自 registry.default_config，api_key 恒为空串不回显）",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否启用（false 时读路径整行回落 env/registry 默认）",
        ),
        sa.Column(
            "note",
            sa.String(255),
            nullable=True,
            comment="备注",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("ai_model_profiles_pkey")),
        schema="safety",
        comment="AI 模型配置表（一行一组配置，DB 为唯一权威）",
    )
    op.create_index(
        "uq_ai_model_profiles_profile",
        "ai_model_profiles",
        ["profile"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_ai_model_profiles_profile",
        "ai_model_profiles",
        ["profile"],
        schema="safety",
    )

    op.create_table(
        "ai_config_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "profile",
            sa.String(32),
            nullable=False,
            comment="profile key",
        ),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="动作: update/enable/disable",
        ),
        sa.Column(
            "before_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更前（compact，api_key 已脱敏为 ****后4位）",
        ),
        sa.Column(
            "after_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更后（compact，api_key 已脱敏为 ****后4位）",
        ),
        sa.Column(
            "operator_name",
            sa.String(128),
            nullable=True,
            comment="操作人 name",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("ai_config_audits_pkey")),
        schema="safety",
        comment="AI 配置变更审计表（append-only）",
    )
    op.create_index(
        "idx_ai_config_audits_profile_created",
        "ai_config_audits",
        ["profile", "created_at"],
        schema="safety",
    )
    op.create_index(
        "idx_ai_config_audits_created",
        "ai_config_audits",
        ["created_at"],
        schema="safety",
    )

    # ── 播种：5 行（值从 registry 单向导出，勿手抄）──
    op.bulk_insert(ai_model_profiles, _profile_seed_rows())


def downgrade() -> None:
    op.drop_index(
        "idx_ai_config_audits_created",
        table_name="ai_config_audits",
        schema="safety",
    )
    op.drop_index(
        "idx_ai_config_audits_profile_created",
        table_name="ai_config_audits",
        schema="safety",
    )
    op.drop_table("ai_config_audits", schema="safety")
    op.drop_index(
        "ix_ai_model_profiles_profile",
        table_name="ai_model_profiles",
        schema="safety",
    )
    op.drop_index(
        "uq_ai_model_profiles_profile",
        table_name="ai_model_profiles",
        schema="safety",
    )
    op.drop_table("ai_model_profiles", schema="safety")
