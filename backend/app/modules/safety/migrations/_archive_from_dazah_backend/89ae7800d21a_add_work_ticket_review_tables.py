"""add work_ticket_review tables

新增作业票审核两张表（safety schema）：
  - safety.work_ticket_reviews          每日审核摘要
  - safety.work_ticket_review_violations 逐票违规明细

Revision ID: 89ae7800d21a
Revises: 1f7df0201945
Create Date: 2026-08-26 09:17:14.142701
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '89ae7800d21a'
down_revision: str | None = '1f7df0201945'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # ── 表 1：work_ticket_reviews（每日审核摘要）──
    op.create_table(
        "work_ticket_reviews",
        sa.Column("date", sa.Date(), nullable=False, comment="审核日期（作业日期，Asia/Shanghai）"),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False, comment="当日拉取到的标准 8 类作业票总数"),
        sa.Column("reviewed", sa.Integer(), server_default="0", nullable=False, comment="已具备开始时间、纳入规则审核的票数"),
        sa.Column("violation_count", sa.Integer(), server_default="0", nullable=False, comment="违规票数（含违规条数的票数，非条数）"),
        sa.Column("compliant_count", sa.Integer(), server_default="0", nullable=False, comment="合格票数（有开始时间且无任何违规）"),
        sa.Column("data_insufficient", sa.Integer(), server_default="0", nullable=False, comment="数据不足票数（缺开始时间/关键字段，审核窗口未满足）"),
        sa.Column("status", sa.String(length=16), server_default="success", nullable=False, comment="审核状态: pending/success/failed"),
        sa.Column("raw_json", sa.JSON(), nullable=True, comment="当日平台原始工作流数据快照"),
        sa.Column("report_markdown", sa.Text(), nullable=True, comment="生成的可读 Markdown 报告"),
        sa.Column("pushed", sa.Boolean(), server_default="false", nullable=False, comment="是否已推送群"),
        sa.Column("push_message_id", sa.String(length=64), nullable=True, comment="飞书卡片 message_id"),
        sa.Column("error", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True, comment="完成时间"),
        # ── BaseModel 公共字段 ──
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index(
        "uq_work_ticket_reviews_date", "work_ticket_reviews", ["date"],
        unique=True, schema="safety", postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_work_ticket_reviews_date", "work_ticket_reviews", ["date"],
        unique=False, schema="safety",
    )

    # ── 表 2：work_ticket_review_violations（逐票违规明细）──
    op.create_table(
        "work_ticket_review_violations",
        sa.Column("review_id", sa.UUID(), nullable=False, comment="逻辑外键 → work_ticket_reviews.id（不建物理 FK）"),
        sa.Column("ticket_no", sa.String(length=64), nullable=False, comment="作业票号"),
        sa.Column("ticket_type", sa.String(length=32), nullable=False, comment="作业类型: hot_work/confined_space/height_work/..."),
        sa.Column("rule_no", sa.String(length=32), nullable=False, comment="规则编号: TIME_ORDER/GAS_VALIDITY/DURATION/GAS_INTERVAL"),
        sa.Column("rule_name", sa.String(length=64), nullable=False, comment="规则中文名"),
        sa.Column("detail", sa.Text(), nullable=False, comment="违规/不适用描述"),
        sa.Column("key_times", sa.JSON(), nullable=True, comment="关键时间点 {申请/审批/开始/结束/验收/气体分析等}"),
        sa.Column("not_applicable", sa.Boolean(), server_default="false", nullable=False, comment="true 表示该规则对该票「不适用」而非违规"),
        # ── BaseModel 公共字段 ──
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index(
        "ix_wt_review_violations_review_id", "work_ticket_review_violations", ["review_id"],
        unique=False, schema="safety",
    )
    op.create_index(
        "ix_wt_review_violations_ticket_no", "work_ticket_review_violations", ["ticket_no"],
        unique=False, schema="safety",
    )
    op.create_index(
        "ix_wt_review_violations_rule_no", "work_ticket_review_violations", ["rule_no"],
        unique=False, schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wt_review_violations_rule_no", table_name="work_ticket_review_violations", schema="safety",
    )
    op.drop_index(
        "ix_wt_review_violations_ticket_no", table_name="work_ticket_review_violations", schema="safety",
    )
    op.drop_index(
        "ix_wt_review_violations_review_id", table_name="work_ticket_review_violations", schema="safety",
    )
    op.drop_table("work_ticket_review_violations", schema="safety")
    op.drop_index("uq_work_ticket_reviews_date", table_name="work_ticket_reviews", schema="safety", postgresql_where=sa.text("is_deleted = false"))
    op.drop_index("ix_work_ticket_reviews_date", table_name="work_ticket_reviews", schema="safety")
    op.drop_table("work_ticket_reviews", schema="safety")
