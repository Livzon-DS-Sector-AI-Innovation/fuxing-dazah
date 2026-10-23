"""safety 作业票整改复查表（workticket-rectify，每日10点审昨日+复查前日问题）

《作业票判定规则》2026-10-23 新口径：每日 10 点审核昨日作业票，并复查
前一日审核结果中问题票是否整改。本表一行 = 一次复查中一张问题票的结论；
唯一 (source_review_date, ticket_no) partial 支撑重跑幂等覆盖。无种子。

Revision ID: d4c8e2f6a1b5
Revises: b7d2f4a8c1e9
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "d4c8e2f6a1b5"
down_revision: str | None = "b7d2f4a8c1e9"
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
        "work_ticket_rectify_checks",
        sa.Column(
            "source_review_date", sa.Date(), nullable=False,
            comment="被复查的审核日期（该审核覆盖的作业日期）",
        ),
        sa.Column(
            "checked_date", sa.Date(), nullable=False,
            comment="复查执行日（Asia/Shanghai）",
        ),
        sa.Column("ticket_no", sa.String(length=64), nullable=False, comment="作业票号"),
        sa.Column(
            "ticket_type", sa.String(length=32), nullable=False,
            comment="作业类型: hot_work/confined_space/height_work/...",
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="unrectified", nullable=False,
            comment="rectified(已整改) / unrectified(未整改) / uncheckable(无法复查)",
        ),
        sa.Column(
            "rule_results", sa.JSON(), nullable=True,
            comment="逐规则比对 [{rule_no, rule_name, yesterday_detail, resolved, today_detail}]",
        ),
        sa.Column(
            "note", sa.Text(), nullable=True,
            comment="无法复查原因（拉取失败/缺原始数据等）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_work_ticket_rectify_date_ticket",
        "work_ticket_rectify_checks",
        ["source_review_date", "ticket_no"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_work_ticket_rectify_source_date",
        "work_ticket_rectify_checks",
        ["source_review_date"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_ticket_rectify_source_date",
        table_name="work_ticket_rectify_checks", schema="safety",
    )
    op.drop_index(
        "uq_work_ticket_rectify_date_ticket",
        table_name="work_ticket_rectify_checks", schema="safety",
    )
    op.drop_table("work_ticket_rectify_checks", schema="safety")
