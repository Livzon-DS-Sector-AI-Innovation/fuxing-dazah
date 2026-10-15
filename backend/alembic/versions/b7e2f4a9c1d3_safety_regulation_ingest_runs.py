"""safety regulation_ingest_runs（法规收录 run 级留痕，契约①接收侧）

一次 ragplus 候选批次推送一行：幂等锚点=source_run_id（唯一索引仅约束
status='completed' 的行，skipped/failed 可重试多行）；逐条结果 / 契约②
回执 / 事件信封 jsonb 落行内。无种子。

Revision ID: b7e2f4a9c1d3
Revises: a3c5e7f9b1d2
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "b7e2f4a9c1d3"
down_revision: str | None = "a3c5e7f9b1d2"
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
        "regulation_ingest_runs",
        sa.Column(
            "source_run_id",
            sa.String(length=128),
            nullable=False,
            comment="ragplus 侧爬取 run_id（幂等锚点）",
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            server_default="push",
            nullable=False,
            comment="触发来源: push=契约①推送 | reconcile=对账巡检补处理",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="completed",
            nullable=False,
            comment="completed=处理完成 | skipped_disabled=总闸关闭跳过 | failed=处理链异常",
        ),
        sa.Column(
            "received_count", sa.Integer(), server_default="0", nullable=False,
            comment="批内候选数",
        ),
        sa.Column(
            "duplicate_count", sa.Integer(), server_default="0", nullable=False,
            comment="预去重命中数",
        ),
        sa.Column(
            "pending_count", sa.Integer(), server_default="0", nullable=False,
            comment="待处理数（AI 超限/未判定）",
        ),
        sa.Column(
            "promoted_count", sa.Integer(), server_default="0", nullable=False,
            comment="判定相关并收录成功数",
        ),
        sa.Column(
            "rejected_count", sa.Integer(), server_default="0", nullable=False,
            comment="判定不相关数",
        ),
        sa.Column(
            "failed_count", sa.Integer(), server_default="0", nullable=False,
            comment="处理错误数",
        ),
        sa.Column(
            "ai_tokens_used", sa.Integer(), server_default="0", nullable=False,
            comment="本批 AI token 消耗",
        ),
        sa.Column(
            "items_result", JSONB(), nullable=True,
            comment="逐条结果 [{candidate_id, action_taken, reason, ...}]",
        ),
        sa.Column(
            "receipts", JSONB(), nullable=True, comment="契约②生命周期回执结果",
        ),
        sa.Column(
            "event_envelope", JSONB(), nullable=True,
            comment="regulation.updated 事件信封（成功路径）",
        ),
        sa.Column(
            "error_summary", sa.Text(), nullable=True,
            comment="失败摘要（截断 500 字符）",
        ),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=True,
            comment="本批处理结束时间",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_regulation_ingest_runs_source_run",
        "regulation_ingest_runs",
        ["source_run_id"],
        schema="safety",
        unique=True,
        postgresql_where=sa.text("is_deleted = false AND status = 'completed'"),
    )
    op.create_index(
        "ix_regulation_ingest_runs_created_at",
        "regulation_ingest_runs",
        ["created_at"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_regulation_ingest_runs_created_at",
        table_name="regulation_ingest_runs",
        schema="safety",
    )
    op.drop_index(
        "uq_regulation_ingest_runs_source_run",
        table_name="regulation_ingest_runs",
        schema="safety",
    )
    op.drop_table("regulation_ingest_runs", schema="safety")
