"""safety org_post_families（#4 岗位族归类资产，无种子）

post_name 软删下部分唯一；source='ai' 行重跑 upsert 覆盖（AI 归类），
source='manual' 行重跑不覆盖（人工确认/修正）。九族枚举见
models/org_post_families.py POST_FAMILIES（§13.1 一次定死）。

Revision ID: b6f2d8e4a9c1
Revises: c4e7a1f9b3d2
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6f2d8e4a9c1"
down_revision: str | None = "c4e7a1f9b3d2"
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
        "org_post_families",
        sa.Column(
            "post_name",
            sa.String(length=128),
            nullable=False,
            comment="岗位名（org_directory postName 原文）",
        ),
        sa.Column(
            "family",
            sa.String(length=32),
            nullable=False,
            comment="标准岗位族（§13.1 九族枚举）",
        ),
        sa.Column(
            "confidence",
            sa.String(length=8),
            server_default="low",
            nullable=False,
            comment="high|mid|low（AI 置信度；manual 行保留原值）",
        ),
        sa.Column(
            "note",
            sa.String(length=512),
            server_default="",
            nullable=False,
            comment="AI 判断说明 / 人工修正备注",
        ),
        sa.Column(
            "source",
            sa.String(length=8),
            server_default="ai",
            nullable=False,
            comment="ai（AI 归类，重跑覆盖）| manual（人工确认/修正，重跑不覆盖）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_org_post_families_post_name",
        "org_post_families",
        ["post_name"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_org_post_families_family",
        "org_post_families",
        ["family"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_org_post_families_family",
        table_name="org_post_families", schema="safety",
    )
    op.drop_index(
        "uq_org_post_families_post_name",
        table_name="org_post_families", schema="safety",
    )
    op.drop_table("org_post_families", schema="safety")
