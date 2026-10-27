"""safety location_district_suggestions（#2 AI 建议映射中间表，无种子）

建议=过程（本表），映射=资产（location_district_map 不动）：AI 批量建议落
pending 行，人工确认后由服务写映射表（source='ai_confirmed'）并置 confirmed。
location_text 软删下部分唯一=DB 兜底幂等（同文本至多一条活建议）。

Revision ID: c4e7a1f9b3d2
Revises: d731d330b6bb
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e7a1f9b3d2"
down_revision: str | None = "d731d330b6bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    op.create_table(
        "location_district_suggestions",
        sa.Column(
            "location_text",
            sa.String(length=128),
            nullable=False,
            comment="地点/部位文本（unmapped 归一原文）",
        ),
        sa.Column(
            "count",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="近 N 天出现事件次数（收集时累计）",
        ),
        sa.Column(
            "kinds",
            sa.JSON(),
            server_default="[]",
            nullable=False,
            comment="来源种类（job/fire/central 去重）",
        ),
        sa.Column(
            "dist_id",
            sa.String(length=64),
            nullable=True,
            comment="建议分区 distId（AI 无法判断为 null）",
        ),
        sa.Column(
            "confidence",
            sa.String(length=8),
            server_default="low",
            nullable=False,
            comment="high|mid|low（mid=AI 输出 medium 归一）",
        ),
        sa.Column(
            "reason",
            sa.String(length=512),
            server_default="",
            nullable=False,
            comment="AI 判断理由（引用分区名/厂区常识）",
        ),
        sa.Column(
            "batch_id",
            sa.String(length=32),
            nullable=False,
            comment="扫描批次号（uuid 截断，排查用）",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
            comment="pending（待确认）| confirmed（已入映射表）| ignored（人工忽略）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_location_district_suggestions_text",
        "location_district_suggestions",
        ["location_text"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_location_district_suggestions_status",
        "location_district_suggestions",
        ["status"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_location_district_suggestions_status",
        table_name="location_district_suggestions", schema="safety",
    )
    op.drop_index(
        "uq_location_district_suggestions_text",
        table_name="location_district_suggestions", schema="safety",
    )
    op.drop_table("location_district_suggestions", schema="safety")
