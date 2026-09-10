"""add ai_scenario_configs, ai_scenario_config_audits tables (no seed)

Revision ID: ai_scenario001b2c3d4e5
Revises: ai_config001b2c3d4e5
Create Date: 2026-08-31 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_scenario001b2c3d4e5"
down_revision: str | None = "ai_config001b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table(
        "ai_scenario_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scenario",
            sa.String(64),
            nullable=False,
            comment="场景 key（registry 注册，DB 只能改值不能新增场景）",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否启用（false = 熔断，统一入口抛 ScenarioDisabledError）",
        ),
        sa.Column(
            "model_profile",
            sa.String(32),
            nullable=True,
            comment="绑定 profile 名（text/text_backup/vision/embedding/rerank）；NULL = 按场景默认",
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
        sa.PrimaryKeyConstraint("id", name=op.f("ai_scenario_configs_pkey")),
        schema="safety",
        comment="AI 场景配置表（一行一场景；缺行 = 默认开启，不播种）",
    )
    op.create_index(
        "uq_ai_scenario_configs_scenario",
        "ai_scenario_configs",
        ["scenario"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_ai_scenario_configs_scenario",
        "ai_scenario_configs",
        ["scenario"],
        schema="safety",
    )

    op.create_table(
        "ai_scenario_config_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scenario",
            sa.String(64),
            nullable=False,
            comment="对应场景",
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
            comment="变更前（compact，{enabled, model_profile, note}，无密钥）",
        ),
        sa.Column(
            "after_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更后（compact，{enabled, model_profile, note}，无密钥）",
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
        sa.PrimaryKeyConstraint("id", name=op.f("ai_scenario_config_audits_pkey")),
        schema="safety",
        comment="AI 场景配置变更审计表（append-only；相位无密钥，无需脱敏）",
    )
    op.create_index(
        "idx_ai_scenario_config_audits_scenario_created",
        "ai_scenario_config_audits",
        ["scenario", "created_at"],
        schema="safety",
    )
    op.create_index(
        "idx_ai_scenario_config_audits_created",
        "ai_scenario_config_audits",
        ["created_at"],
        schema="safety",
    )

    # 不播种（backend-design §1.4）：缺行 = 默认开启，无歧义；registry 只做纯运行时 fallback


def downgrade() -> None:
    op.drop_index(
        "idx_ai_scenario_config_audits_created",
        table_name="ai_scenario_config_audits",
        schema="safety",
    )
    op.drop_index(
        "idx_ai_scenario_config_audits_scenario_created",
        table_name="ai_scenario_config_audits",
        schema="safety",
    )
    op.drop_table("ai_scenario_config_audits", schema="safety")
    op.drop_index(
        "ix_ai_scenario_configs_scenario",
        table_name="ai_scenario_configs",
        schema="safety",
    )
    op.drop_index(
        "uq_ai_scenario_configs_scenario",
        table_name="ai_scenario_configs",
        schema="safety",
    )
    op.drop_table("ai_scenario_configs", schema="safety")
