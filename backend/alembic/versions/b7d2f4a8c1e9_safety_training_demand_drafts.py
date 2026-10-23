"""safety training_demand_drafts（S6 二期链1：年度培训需求草案表）

DESIGN 二期 §4.3：AI 五源生成草案先落本表供评审，采纳后才写 Bitable
培训表（防草案污染 D3-05 完成率分母）。同年重生成=替换 draft 行，
adopted/rejected 保留。无种子。

Revision ID: b7d2f4a8c1e9
Revises: e8d2f6b4a9c1
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d2f4a8c1e9"
down_revision: str | None = "e8d2f6b4a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
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
        "training_demand_drafts",
        sa.Column("year", sa.Integer(), nullable=False, comment="计划年度"),
        sa.Column(
            "position", sa.String(length=255), nullable=False,
            server_default="", comment="岗位（采纳时拆分写台账组织部门多选列）",
        ),
        sa.Column("topic", sa.String(length=500), nullable=False, comment="培训主题"),
        sa.Column("suggested_hours", sa.Float(), nullable=True, comment="建议学时"),
        sa.Column(
            "form", sa.String(length=16), nullable=True,
            comment="建议形式：线下/线上/实操",
        ),
        sa.Column(
            "audience", sa.Text(), nullable=False, server_default="",
            comment="对象说明",
        ),
        sa.Column(
            "basis", sa.Text(), nullable=False, server_default="",
            comment="可溯源依据（AI 只能引用输入中出现过的行为/类别/次数/法规标题）",
        ),
        sa.Column(
            "is_statutory_gap", sa.Boolean(), nullable=False,
            server_default="false",
            comment="法定缺口行（新员工≥72h/年度再培训≥20h/安管≥16h）",
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="draft",
            comment="draft=草案 / adopted=已采纳 / rejected=已驳回",
        ),
        sa.Column(
            "adopted_record_id", sa.String(length=128), nullable=True,
            comment="采纳后 Bitable 培训表行 record_id",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_training_demand_drafts_year_status",
        "training_demand_drafts",
        ["year", "status"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_training_demand_drafts_year_status",
        table_name="training_demand_drafts", schema="safety",
    )
    op.drop_table("training_demand_drafts", schema="safety")
