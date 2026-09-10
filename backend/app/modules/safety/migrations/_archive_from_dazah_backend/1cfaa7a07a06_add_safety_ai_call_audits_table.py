"""add safety ai_call_audits table

Revision ID: 1cfaa7a07a06
Revises: 9a780d338ace
Create Date: 2026-07-15 10:34:39.848163
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1cfaa7a07a06'
down_revision: str | None = '9a780d338ace'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table(
        "ai_call_audits",
        # ── BaseModel 公共字段 ──
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        # ── 链路 ──
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        # ── 主体 ──
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_name", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        # ── 调用 ──
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("input_truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("output_truncated", sa.Boolean(), server_default="false", nullable=False),
        # ── 量化 ──
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        # ── 结果与依据 ──
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("degradation_level", sa.String(length=32), nullable=True),
        sa.Column("cited_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("guard_hits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index("idx_ai_audits_scenario_created", "ai_call_audits", ["scenario", "created_at"], schema="safety")
    op.create_index("idx_ai_audits_resource", "ai_call_audits", ["resource_type", "resource_id"], schema="safety")
    op.create_index("idx_ai_audits_trace", "ai_call_audits", ["trace_id"], schema="safety")
    op.create_index("idx_ai_audits_created_at", "ai_call_audits", ["created_at"], schema="safety")


def downgrade() -> None:
    op.drop_index("idx_ai_audits_created_at", table_name="ai_call_audits", schema="safety")
    op.drop_index("idx_ai_audits_trace", table_name="ai_call_audits", schema="safety")
    op.drop_index("idx_ai_audits_resource", table_name="ai_call_audits", schema="safety")
    op.drop_index("idx_ai_audits_scenario_created", table_name="ai_call_audits", schema="safety")
    op.drop_table("ai_call_audits", schema="safety")
