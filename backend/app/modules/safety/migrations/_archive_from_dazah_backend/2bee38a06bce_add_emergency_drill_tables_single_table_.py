"""add emergency drill tables (single-table model)

Revision ID: 2bee38a06bce
Revises: 8f2e8deae727
Create Date: 2026-07-23 15:25:55.466883
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '2bee38a06bce'
down_revision: str | None = '8f2e8deae727'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Drop old emergency_drill_plans (replaced by single-table model) ──
    op.execute("DROP TABLE IF EXISTS safety.emergency_drill_plans CASCADE")

    # ── 2. Rebuild emergency_drill_records ──

    # Drop old columns
    old_columns = [
        "commander", "plan_no", "corrective_actions", "coordination_evaluation",
        "process_description", "issues_found", "attachments", "scenario_category",
        "executed_at", "start_time", "plan_adequacy", "participants_detail",
        "assessment_grade", "end_time", "plan_suitability", "effectiveness_summary",
        "recorded_by", "location", "participants_count", "record_no",
        "assessment_score", "photos", "title", "plan_id", "supplies_status",
    ]
    for col in old_columns:
        op.execute(f"ALTER TABLE safety.emergency_drill_records DROP COLUMN IF EXISTS {col}")

    # Add new plan-stage columns
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS plan_time VARCHAR(64)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS plan_time_ref DATE")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS drill_content TEXT")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS organizer VARCHAR(256)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS organizer_person VARCHAR(256)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS participants TEXT")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS coop_department VARCHAR(256)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS duration VARCHAR(64)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS alert_person VARCHAR(256)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS alert_person_data JSONB")

    # Add new execution-stage columns
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS execution_time DATE")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS drill_plan_file JSONB")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS signin_file JSONB")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS eval_form_file JSONB")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS drill_record_file JSONB")

    # Add new review-stage columns
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS issues TEXT")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS rectification_person VARCHAR(128)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS rectification_person_data JSONB")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS confirmer VARCHAR(128)")
    op.execute("ALTER TABLE safety.emergency_drill_records ADD COLUMN IF NOT EXISTS confirmer_data JSONB")

    # Adjust drill_type width & make status nullable (was NOT NULL with server_default)
    op.execute("ALTER TABLE safety.emergency_drill_records ALTER COLUMN drill_type TYPE VARCHAR(64)")
    op.execute("ALTER TABLE safety.emergency_drill_records ALTER COLUMN status DROP NOT NULL")
    op.execute("ALTER TABLE safety.emergency_drill_records ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE safety.emergency_drill_records ALTER COLUMN feishu_record_id TYPE VARCHAR(64)")

    # Rebuild indexes (drop old + new names for idempotency)
    for old_idx in ["idx_drill_records_department", "idx_drill_records_executed_at",
                    "idx_drill_records_feishu_record", "idx_drill_records_plan_id",
                    "idx_drill_records_scenario", "idx_drill_records_status",
                    "idx_drill_department", "idx_drill_execution_time",
                    "idx_drill_feishu_record", "idx_drill_status"]:
        op.execute(f"DROP INDEX IF EXISTS safety.{old_idx}")
    op.create_index("idx_drill_department", "emergency_drill_records", ["department"],
                    schema="safety")
    op.create_index("idx_drill_execution_time", "emergency_drill_records", ["execution_time"],
                    schema="safety")
    op.create_index("idx_drill_feishu_record", "emergency_drill_records", ["feishu_record_id"],
                    schema="safety")
    op.create_index("idx_drill_status", "emergency_drill_records", ["status"],
                    schema="safety")

    # ── 3. emergency_drill_documents: rename status → doc_status ──
    op.execute("ALTER TABLE safety.emergency_drill_documents ADD COLUMN IF NOT EXISTS doc_status VARCHAR(16) DEFAULT 'draft'")
    op.execute("ALTER TABLE safety.emergency_drill_documents DROP COLUMN IF EXISTS status")
    op.execute("DROP INDEX IF EXISTS safety.idx_drill_docs_type")

    # ── 4. Create drill_hazard_links ──
    op.create_table(
        "drill_hazard_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("drill_record_id", sa.Uuid(), nullable=False, comment="EmergencyDrillRecord.id"),
        sa.Column("hazard_report_id", sa.Uuid(), nullable=False, comment="HazardReport.id"),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
    op.create_index("idx_dhl_drill", "drill_hazard_links", ["drill_record_id"], schema="safety")
    op.create_index("idx_dhl_hazard", "drill_hazard_links", ["hazard_report_id"], schema="safety")


def downgrade() -> None:
    op.drop_index("idx_dhl_hazard", table_name="drill_hazard_links", schema="safety")
    op.drop_index("idx_dhl_drill", table_name="drill_hazard_links", schema="safety")
    op.drop_table("drill_hazard_links", schema="safety")

    op.execute("ALTER TABLE safety.emergency_drill_documents ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'draft'")
    op.execute("ALTER TABLE safety.emergency_drill_documents DROP COLUMN IF EXISTS doc_status")

    # Drill record columns are not restored in downgrade (one-way migration)
