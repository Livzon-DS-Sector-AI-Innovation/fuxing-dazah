"""add urs review tables

URS 智能审核（EHS 设备采购合规审核）：urs_reports / urs_standard_items / urs_review_documents

Revision ID: d2e3f4a5b6c7
Revises: b7c8d9e0f1a2
Create Date: 2026-08-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: str | None = 'b7c8d9e0f1a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # ════════════════════════════════════════════════════════════════
    # 1. urs_reports — URS 审核主表
    # ════════════════════════════════════════════════════════════════
    op.create_table(
        "urs_reports",
        # ── BaseModel 公共字段 ──
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        # ── 编号与基本信息 ──
        sa.Column("urs_no", sa.String(length=64), nullable=False),
        sa.Column("equipment_name", sa.String(length=256), nullable=False),
        sa.Column("equipment_category", sa.String(length=64), nullable=True),
        sa.Column("department", sa.String(length=128), nullable=True),
        sa.Column("applicant_name", sa.String(length=128), nullable=True),
        sa.Column("applicant_open_id", sa.String(length=128), nullable=True),
        sa.Column("procurement_purpose", sa.String(length=32), nullable=True),
        sa.Column("urs_content", sa.Text(), nullable=True),
        sa.Column("attachment_path", sa.String(length=500), nullable=True),
        sa.Column("source_chat_id", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # ── 五维风险画像 ──
        sa.Column("risk_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall_risk_level", sa.String(length=16), nullable=True),
        sa.Column("risk_profile_reasoning", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("human_review_comment", sa.Text(), nullable=True),
        # ── AI 审核结论 ──
        sa.Column("review_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("grade", sa.String(length=2), nullable=True),
        sa.Column("conclusion", sa.String(length=16), nullable=True),
        sa.Column("rectification_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # ── 状态机与 AI 流程状态 ──
        sa.Column("review_status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("ai_error_message", sa.Text(), nullable=True),
        sa.Column("ai_assessment_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("ai_assessment_completed_at", sa.DateTime(timezone=True), nullable=True),
        # ── 申诉 ──
        sa.Column("appeal_reason", sa.Text(), nullable=True),
        sa.Column("appeal_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # ── 飞书通知追踪 ──
        sa.Column("notify_status", sa.String(length=16), nullable=True),
        sa.Column("notify_error", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index(
        "uq_urs_reports_urs_no", "urs_reports", ["urs_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema="safety",
    )
    op.create_index("idx_urs_reports_department", "urs_reports", ["department"], schema="safety")
    op.create_index("idx_urs_reports_status", "urs_reports", ["review_status"], schema="safety")

    # ════════════════════════════════════════════════════════════════
    # 2. urs_standard_items — 审核标准条目（适配 + 逐条审核）
    # ════════════════════════════════════════════════════════════════
    op.create_table(
        "urs_standard_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("urs_id", sa.Uuid(), nullable=False),
        sa.Column("item_no", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("risk_dimension", sa.String(length=16), nullable=True),
        sa.Column("standard_title", sa.String(length=256), nullable=False),
        sa.Column("standard_ref", sa.String(length=256), nullable=True),
        sa.Column("is_veto", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source", sa.String(length=16), server_default="seed", nullable=False),
        sa.Column("applicability", sa.String(length=16), server_default="recommended", nullable=False),
        sa.Column("applicability_reason", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("ai_suggestion", sa.Text(), nullable=True),
        sa.Column("rectification_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index("idx_urs_items_urs", "urs_standard_items", ["urs_id"], schema="safety")
    op.create_index("idx_urs_items_applicability", "urs_standard_items", ["applicability"], schema="safety")

    # ════════════════════════════════════════════════════════════════
    # 3. urs_review_documents — AI 审核报告文档
    # ════════════════════════════════════════════════════════════════
    op.create_table(
        "urs_review_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("resource_type", sa.String(length=32), server_default="urs_report", nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generation_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cited_regulations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_model", sa.String(length=64), nullable=True),
        sa.Column("ai_tokens_used", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("feishu_doc_id", sa.String(length=64), nullable=True),
        sa.Column("feishu_doc_url", sa.String(length=512), nullable=True),
        sa.Column("feishu_doc_status", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index(
        "idx_urs_docs_resource", "urs_review_documents", ["resource_type", "resource_id"], schema="safety",
    )


def downgrade() -> None:
    op.drop_index("idx_urs_docs_resource", table_name="urs_review_documents", schema="safety")
    op.drop_table("urs_review_documents", schema="safety")

    op.drop_index("idx_urs_items_applicability", table_name="urs_standard_items", schema="safety")
    op.drop_index("idx_urs_items_urs", table_name="urs_standard_items", schema="safety")
    op.drop_table("urs_standard_items", schema="safety")

    op.drop_index("uq_urs_reports_urs_no", table_name="urs_reports", schema="safety")
    op.drop_index("idx_urs_reports_status", table_name="urs_reports", schema="safety")
    op.drop_index("idx_urs_reports_department", table_name="urs_reports", schema="safety")
    op.drop_table("urs_reports", schema="safety")
