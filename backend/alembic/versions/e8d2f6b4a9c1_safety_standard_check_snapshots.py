"""safety standard_check_snapshots（S1 体系标准符合性周期定格，二期）

DESIGN §3.3：周期末 snapshot 落 DB——绩效评定/标准化自评/迎检直接导出。
行冗余快照清单列（条款/目标值/依据/部门等），清单后续修订不篡改历史；
唯一 (standard_no, period_key) 支撑重复定格 upsert 幂等。无种子。

Revision ID: e8d2f6b4a9c1
Revises: b3c7d9e2f4a6
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "e8d2f6b4a9c1"
down_revision: str | None = "b3c7d9e2f4a6"
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
        "standard_check_snapshots",
        sa.Column(
            "standard_no", sa.String(length=32), nullable=False,
            comment="标准编号（人编稳定锚点）",
        ),
        sa.Column("year", sa.Integer(), nullable=False, comment="定格对象年"),
        sa.Column(
            "period_key", sa.String(length=16), nullable=False,
            comment="2026 / 2026H1 / 2026-Q3 / 2026-09",
        ),
        sa.Column("metric_key", sa.String(length=64), nullable=True, comment="空=人工核查项"),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("operator", sa.String(length=8), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False,
            comment="achieved/missed/no_data/manual_done/manual_missed"
                    "（in_progress 仅年度/半年项季度中期快照，终版覆盖）",
        ),
        sa.Column(
            "evidence", JSONB(), nullable=True,
            comment="证据引用快照：{window, items, no_data_reason}",
        ),
        sa.Column(
            "frozen_at", sa.DateTime(timezone=True), nullable=False,
            comment="定格时刻（终版覆盖时刷新）",
        ),
        # ── 清单行冗余快照（防清单后续修订篡改历史）──
        sa.Column("clause", sa.Text(), nullable=False, comment="标准条款快照"),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("element", sa.String(length=32), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("unit", sa.String(length=8), nullable=True),
        sa.Column("department", JSONB(), nullable=True, comment="责任部门列表快照"),
        sa.Column("owner", sa.String(length=64), nullable=True),
        sa.Column("manual_result", sa.String(length=8), nullable=True),
        sa.Column("last_done_on", sa.Date(), nullable=True, comment="长周期项锚点快照"),
        sa.Column("actual_display", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True, comment="判定附注（无数据原因等）"),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "standard_no", "period_key",
            name="uq_standard_check_snapshots_no_period",
        ),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_standard_check_snapshots_year_period",
        "standard_check_snapshots",
        ["year", "period_key"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_standard_check_snapshots_year_period",
        table_name="standard_check_snapshots", schema="safety",
    )
    op.drop_table("standard_check_snapshots", schema="safety")
