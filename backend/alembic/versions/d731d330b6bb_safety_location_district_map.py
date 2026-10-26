"""safety 地点→风险分区映射表（facility-map F2，初灌走 seed 脚本）

location_district_map：地点文本 → 3.x 平台风险分区 distId 的确认映射资产。
初灌=64 分区名原文+人工同义词（backend/scripts/seed_location_district_map.py，
ON CONFLICT DO NOTHING 幂等）；运行时只读（pins 端点查询）。无种子。

Revision ID: d731d330b6bb
Revises: d4c8e2f6a1b5
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d731d330b6bb"
down_revision: str | None = "d4c8e2f6a1b5"
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
        "location_district_map",
        sa.Column(
            "location_text",
            sa.String(length=128),
            nullable=False,
            comment="地点/部位文本（分区名原文或人工同义词）",
        ),
        sa.Column(
            "dist_id",
            sa.String(length=64),
            nullable=False,
            comment="3.x 平台风险分区 distId（无本地主表，不外键）",
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            server_default="manual",
            nullable=False,
            comment="manual（人工）/ ai_confirmed（AI 建议确认，另议）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_location_district_map_text",
        "location_district_map",
        ["location_text"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_location_district_map_dist_id",
        "location_district_map",
        ["dist_id"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_location_district_map_dist_id",
        table_name="location_district_map", schema="safety",
    )
    op.drop_index(
        "uq_location_district_map_text",
        table_name="location_district_map", schema="safety",
    )
    op.drop_table("location_district_map", schema="safety")
